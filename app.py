from flask import Flask, request, jsonify
import requests
import speech_recognition as sr
import time
import re
from pymongo import MongoClient
from threading import Thread
from flask_cors import CORS

# Flask setup
app = Flask(__name__)
CORS(app)
# ESP8266 configuration
ESP8266_IP = "192.168.15.86"  # Replace with actual IP
PORT = 80  # HTTP port

# MongoDB Atlas Connection
username = "soumava"
password = "Souhardo303"
db_uri = f"mongodb+srv://{username}:{password}@minorproject303.6xkxa.mongodb.net/"
client = MongoClient(db_uri, serverSelectionTimeoutMS=5000)
db = client["souhardosoumava303"]
devices_collection = db["devices"]
logs_collection = db["logs"]

# Device states tracking
device_state = {}

# Function to send command to ESP8266
def send_command(device_name, action):
    try:
        url = f"http://{ESP8266_IP}:{PORT}/command?device_name={device_name}&action={action}"
        headers = {"Connection": "close"}  # Ensure connection closes after request
        response = requests.get(url, headers=headers, timeout=5)
        if response.status_code == 200:
            print(f"Response from ESP8266 for {device_name} {action}: {response.text}")
        else:
            print("Failed to send command. HTTP Code:", response.status_code)
    except requests.exceptions.RequestException as e:
        print("Error sending command:", e)

# Function to fetch all valid device names from the database
def get_valid_devices():
    return [device["device_name"] for device in devices_collection.find({}, {"device_name": 1})]

# Function to handle heavy device switching
def handle_heavy_device_switch(device_name, action):
    device_data = devices_collection.find_one({"device_name": device_name})
    
    if not device_data:
        print(f"Device {device_name} not found in the database.")
        return

    device_type = device_data.get("device_type", "light")  # Default to "light"

    # If it's a heavy device, check for existing active heavy devices
    if device_type == "heavy":
        active_heavy_device = next(
            (dev for dev, state in device_state.items() if state == "on" and 
             devices_collection.find_one({"device_name": dev}).get("device_type") == "heavy"), 
            None
        )

        if active_heavy_device:
            print(f"Warning: Another heavy device ({active_heavy_device}) is already on.")
            print(f"Do you want to turn off {active_heavy_device} and turn on {device_name}? (say 'proceed' or 'cancel')")
            response = recognize_voice()
            if response and "proceed" in response:
                print(f"Turning off {active_heavy_device} and turning on {device_name}.")
                send_command(active_heavy_device, "off")
                device_state[active_heavy_device] = "off"
                send_command(device_name, action)
                device_state[device_name] = action
            elif response and "cancel" in response:
                print("Operation canceled.")
        else:
            send_command(device_name, action)
            device_state[device_name] = action
    else:
        # Non-heavy device, execute normally
        send_command(device_name, action)
        device_state[device_name] = action

# Function to process voice commands dynamically
def process_device_command(command):
    valid_actions = ["on", "off"]
    valid_devices = get_valid_devices()  # Fetch device names from database

    # Regex pattern to match any valid device and action
    pattern = rf"(turn|switch)\s+(on|off)\s+(the\s+)?({'|'.join(valid_devices)})"
    match = re.search(pattern, command)

    if match:
        action = match.group(2)
        device_name = match.group(4)  # Extracted device name

        if action not in valid_actions:
            print(f"Invalid action '{action}'. Use 'on' or 'off'.")
            return

        # Handle heavy device logic
        handle_heavy_device_switch(device_name, action)
    else:
        print("Could not recognize the command. Make sure it's in the correct format.")

# Function to recognize voice commands
def recognize_voice():
    recognizer = sr.Recognizer()
    microphone = sr.Microphone()

    try:
        with microphone as source:
            recognizer.adjust_for_ambient_noise(source)
            print("Listening for a command (say 'Hey Alex' to wake up)...")
            audio = recognizer.listen(source)

        command = recognizer.recognize_google(audio).lower()
        print("You said:", command)
        return command

    except sr.UnknownValueError:
        print("Sorry, I didn't catch that. Please try again.")
        return None
    except sr.RequestError as e:
        print("Could not request results from the service:", e)
        return None

# Flask route to receive commands from the web
@app.route('/command', methods=['GET'])
def receive_command():
    data = request.json
    print("Received command:", data)

    if not data:
        print("No data received.")
        return jsonify({"status": "error", "message": "No data received."}), 400

    device_name = data.get("device_name", "").lower()
    action = data.get("action", "").lower()

    if not device_name or not action:
        print("Missing device_name or action.")
        return jsonify({"status": "error", "message": "Missing device_name or action."}), 400
    
    # Process and send the command
    handle_heavy_device_switch(device_name, action)
    process_device_command(device_name, action)
    return jsonify({"status": "success", "message": f"Command sent: {device_name} {action}"})

# Function to start Flask with SSL in a separate thread
def run_flask():
    app.run(host="0.0.0.0", port=5000, ssl_context="adhoc")

# Main program loop
if __name__ == "__main__":
    alex_state = "sleep"  # Initial state of Alex
    print("Starting Flask server...")

    # Run Flask in a separate thread to keep voice recognition active
    flask_thread = Thread(target=run_flask, daemon=True)
    flask_thread.start()
    alex_thread = Thread(target=recognize_voice, daemon=True)
    while True:
        if alex_state == "sleep":
            print("Alex is sleeping...")
            command = recognize_voice()

            if command and "hey alex" in command:
                print("I am listening...")
                alex_state = "awake"
                continue

        elif alex_state == "awake":
            print("Listening for your command...")
            command = recognize_voice()
            if command:
                process_device_command(command)

                print("Command executed. Waiting for next command...")

                # Wait for next command or go back to sleep after 50 seconds of inactivity
                idle_start = time.time()
                while time.time() - idle_start < 50:
                    new_command = recognize_voice()
                    if new_command:
                        command = new_command
                        break
                else:
                    print("No new command. Going to sleep...")
                    alex_state = "sleep"
