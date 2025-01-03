from flask import Flask, render_template, request, jsonify, send_file
import requests
from bs4 import BeautifulSoup
import logging
import bz2
import pandas as pd
from datetime import datetime
import os
import io
import matplotlib.pyplot as plt

app = Flask(__name__)

df = pd.DataFrame()

def process_txt_file(file_content):
    """Process text data content and return a DataFrame."""
    lines = file_content.split('\n')
    data = []
    section = 0

    for line in lines:
        line = line.strip()
        if section == 0 and line.startswith("----------"):
            section = 1
        elif section == 1 and line.startswith("----------"):
            section = 2
        elif section == 2 and not line.startswith("#") and "INFO" not in line and line.strip():
            data.append(line.split())

    if not data:
        return pd.DataFrame()  # Return an empty DataFrame if no data was found

    # Attempt to infer the number of columns based on the length of the first data entry
    if data:
        num_columns = len(data[0])
    else:
        return pd.DataFrame()  # Return empty DataFrame if data is empty

    base_columns = [
        "Routine Code", "Timestamp", "Routine Count", "Repetition Count",
        "Duration", "Integration Time [ms]", "Number of Cycles", "Saturation Index",
        "Filterwheel 1", "Filterwheel 2", "Zenith Angle [deg]", "Zenith Mode",
        "Azimuth Angle [deg]", "Azimuth Mode", "Processing Index", "Target Distance [m]",
        "Electronics Temp [°C]", "Control Temp [°C]", "Aux Temp [°C]", "Head Sensor Temp [°C]",
        "Head Sensor Humidity [%]", "Head Sensor Pressure [hPa]", "Scale Factor", "Uncertainty Indicator"
    ]
    num_base_columns = len(base_columns)
    num_pixel_columns = num_columns - num_base_columns

    # Generate pixel column names based on the excess number of columns
    pixel_columns = [f"Pixel_{i+1}" for i in range(num_pixel_columns)]
    column_names = base_columns + pixel_columns

    # Convert to DataFrame
    global df
    df = pd.DataFrame(data, columns=column_names)
    df["Timestamp"] = pd.to_datetime(df["Timestamp"], errors="coerce")

    return df

def decompress_bz2_file(file_content):
    try:
        decompressed_content = bz2.decompress(file_content).decode("utf-8", errors="replace")
        return decompressed_content
    except Exception as e:
        print(f"Error decompressing file: {e}")
        return ""


def fetch_locations(url):
    response = requests.get(url)
    if response.status_code != 200:
        return []  # Return an empty list if the URL is unreachable or error occurs

    soup = BeautifulSoup(response.content, 'html.parser')
    folders = []
    for link in soup.find_all('a'):
        href = link.get('href')
        if href and href.startswith('./'):
            folder_name = href.strip('/')
            folder_name = href.strip('./')
            if folder_name:  # Ensure it's not empty after stripping
                folders.append(folder_name)
    return folders

@app.route('/')
def index():
    locations = fetch_locations("https://data.ovh.pandonia-global-network.org/")
    return render_template('index.html', locations=locations)

@app.route('/get-devices/', methods=['GET'])
def get_devices():
    selected_location = request.args.get('location')
    if not selected_location:
        return jsonify([])  # Return empty if no location is selected

    url = f"https://data.ovh.pandonia-global-network.org/{selected_location}/"
    try:
        response = requests.get(url)
        if response.status_code == 200:
            soup = BeautifulSoup(response.content, 'html.parser')
            devices = []
            for link in soup.find_all('a'):
                href = link.get('href')
                if href.startswith('./'):
                    device_name = href.strip('./').split('/')[0]  # Extract device name, remove leading './' and trailing '/'
                    if device_name and device_name not in devices:  # Check if device name is non-empty and avoid duplicates
                        devices.append(device_name)
            return jsonify(devices)
        else:
            return jsonify([])  # Return empty list if URL is not reachable
    except requests.RequestException as e:
        print(f"Error fetching devices: {e}")
        return jsonify([])

@app.route('/get-files/', methods=['GET'])
def get_files():
    selected_location = request.args.get('location')
    selected_device = request.args.get('device')
    if not selected_location or not selected_device:
        return jsonify([])  # Return empty if no location or device is selected

    url = f"https://data.ovh.pandonia-global-network.org/{selected_location}/{selected_device}/L0/"
    try:
        response = requests.get(url)
        if response.status_code == 200:
            soup = BeautifulSoup(response.content, 'html.parser')
            files = []
            for link in soup.find_all('a'):
                href = link.get('href')
                if href.startswith('./'):
                    file_name = href.strip('./').split('/')[0]  # Extract file name, remove leading './' and trailing '/'
                    if file_name and file_name not in files:  # Avoid duplicates and ensure the file name is non-empty
                        files.append(file_name)
            return jsonify(files)
        else:
            return jsonify([])  # Return empty list if URL is not reachable or an error occurred
    except requests.RequestException as e:
        print(f"Error fetching files: {e}")
        return jsonify([]) 

@app.route('/download-process-file')
def download_process_file():
    file_url = request.args.get('file_url')
    if not file_url:
        return jsonify({"error": "No file URL provided"}), 400

    try:
        response = requests.get(file_url, stream=True)
        if response.status_code == 200:
            if file_url.endswith('.bz2'):
                file_content = decompress_bz2_file(response.content)
            else:
                file_content = response.content.decode('utf-8', errors='replace')

            # Assume file_content is now a properly decoded string, if not, adjust accordingly
            result_df = process_txt_file(file_content)
            if not result_df.empty:
                result_path = "/tmp/result.csv"
                result_df.to_csv(result_path, index=False)
                return send_file(result_path, as_attachment=True)
            else:
                return jsonify({"error": "Processed data is empty"}), 404
        else:
            return jsonify({"error": "Failed to download file"}), 500
    except Exception as e:
        return jsonify({"error": str(e)}), 500

@app.route('/opaque')
def opaque():
    file_url = request.args.get('file_url')
    if not file_url:
        return jsonify({"error": "No file URL provided"}), 400

    try:
        # Fetch the file content from the URL
        response = requests.get(file_url)
        if response.status_code == 200:
            file_content = response.content
            if file_url.endswith('.bz2'):
                file_content = decompress_bz2_file(file_content)
                if file_content is None:
                    return jsonify({"error": "Failed to decompress data"}), 500
            
            # Process the file content using the custom function
            df = process_txt_file(file_content)

            # Ensure the DataFrame contains the necessary columns
            if 'Filterwheel 2' not in df or 'Routine Code' not in df:
                return jsonify({'error': 'Required columns are missing in the data'}), 400
            
            # Filtering data based on 'Filterwheel 2'
            df_filtered = df[df['Filterwheel 2'].isin([3, 6])]
            if df_filtered.empty:
                return jsonify({'error': 'No data found for specified filter criteria'}), 404
            
            # Plotting
            plt.figure(figsize=(10, 5))
            plt.plot(df_filtered['Routine Code'], df_filtered['Other Data'], marker='o')
            plt.title('Opaque Filter Values')
            plt.xlabel('Routine Code')
            plt.ylabel('Values')
            plt.grid(True)

            # Save the plot to a bytes buffer
            buf = io.BytesIO()
            plt.savefig(buf, format='png')
            buf.seek(0)
            plt.close()

            return send_file(buf, mimetype='image/png')
        else:
            return jsonify({"error": "Failed to download file"}), 500
    except Exception as e:
        return jsonify({"error": str(e)}), 500

@app.route('/open')
def open():
    # Implement the function for the Open chart
    return redirect(url_for('home'))  # Example: redirect back to home

@app.route('/moon_open')
def moon_open():
    # Implement the function for the Moon Open chart
    return redirect(url_for('home'))  # Example: redirect back to home

@app.route('/sun_open')
def sun_open():
    # Implement the function for the Sun Open chart
    return redirect(url_for('home'))  # Example: redirect back to home

@app.route('/all_sensors')
def all_sensors():
    # Implement the function for viewing all sensors
    return redirect(url_for('home'))  # Example: redirect back to home

@app.route('/')
def home():
    return render_template('display_plot.html')


if __name__ == '__main__':
    logging.basicConfig(level=logging.DEBUG)
    app.run(debug=True)