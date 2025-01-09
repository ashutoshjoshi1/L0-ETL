from flask import Flask, render_template, request, jsonify, send_file
import requests
from bs4 import BeautifulSoup
import logging
import bz2
import pandas as pd
from datetime import datetime
import os
import io
import matplotlib
matplotlib.use('agg')
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
        return pd.DataFrame()
    if data:
        num_columns = len(data[0])
    else:
        return pd.DataFrame()  # Return empty DataFrame if data is empty

    # Define the maximum columns to process
    max_columns = 2076
    base_columns = [
        "Routine Code", "Timestamp", "Routine Count", "Repetition Count",
        "Duration", "Integration Time [ms]", "Number of Cycles", "Saturation Index",
        "Filterwheel 1", "Filterwheel 2", "Zenith Angle [deg]", "Zenith Mode",
        "Azimuth Angle [deg]", "Azimuth Mode", "Processing Index", "Target Distance [m]",
        "Electronics Temp [°C]", "Control Temp [°C]", "Aux Temp [°C]", "Head Sensor Temp [°C]",
        "Head Sensor Humidity [%]", "Head Sensor Pressure [hPa]", "Scale Factor", "Uncertainty Indicator"
    ]
    num_base_columns = len(base_columns)
    num_pixel_columns = min(num_columns, max_columns) - num_base_columns

    # Generate pixel column names based on the excess number of columns
    pixel_columns = [f"Pixel_{i+1}" for i in range(num_pixel_columns)]
    column_names = base_columns + pixel_columns

    # Convert to DataFrame
    global df
    df = pd.DataFrame([row[:max_columns] for row in data], columns=column_names[:max_columns])
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
        response = requests.get(file_url)
        if response.status_code == 200:
            file_content = response.content
            if file_url.endswith('.bz2'):
                file_content = decompress_bz2_file(file_content)
                if file_content is None:
                    return jsonify({"error": "Failed to decompress data"}), 500

            df = process_txt_file(file_content)
            df1 = df.iloc[:, 2:2030]

            # Convert all object columns to int
            df1 = df1.apply(lambda col: pd.to_numeric(col, errors='coerce') if col.dtypes == 'object' else col)

            # Optional: Replace NaN values (if any) after conversion with a default value, e.g., 0
            df1 = df1.fillna(0).astype(int)
            df1 = df1[df1['Filterwheel 2'].isin([3, 6])]

            # Ensure selected DataFrame has numeric data
            # df1.apply(pd.to_numeric)
            df1 = df1.iloc[:, 22:2030]


            # Calculate mean across rows (axis=0)
            y = df1.mean(axis=0).tolist()
            print(len(y))
            print(y)
            # Create x-axis values
            x = range(len(y))

            # Plotting logic
            plt.figure(figsize=(30, 15))
            plt.plot(x, y)
            plt.title('Pixel Values for Opaque')
            plt.xlabel('Pixel Number')
            plt.ylabel('Average Pixel Value')
            # plt.grid(True)

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
    file_url = request.args.get('file_url')
    if not file_url:
        return jsonify({"error": "No file URL provided"}), 400

    try:
        response = requests.get(file_url)
        if response.status_code == 200:
            file_content = response.content
            if file_url.endswith('.bz2'):
                file_content = decompress_bz2_file(file_content)
                if file_content is None:
                    return jsonify({"error": "Failed to decompress data"}), 500

            df = process_txt_file(file_content)
            df1 = df.iloc[:, 2:2030]

            # Convert all object columns to int
            df1 = df1.apply(lambda col: pd.to_numeric(col, errors='coerce') if col.dtypes == 'object' else col)

            # Optional: Replace NaN values (if any) after conversion with a default value, e.g., 0
            df1 = df1.fillna(0).astype(int)
            df1 = df1[df1['Filterwheel 1'].isin([1, 2, 4])]
            df1 = df1[df1['Filterwheel 2'].isin([1, 4])]

            # Ensure selected DataFrame has numeric data
            # df1.apply(pd.to_numeric)
            df1 = df1.iloc[:, 22:2030]


            # Calculate mean across rows (axis=0)
            y = df1.mean(axis=0).tolist()
            print(len(y))
            print(y)
            # Create x-axis values
            x = range(len(y))

            # Plotting logic
            plt.figure(figsize=(30, 15))
            plt.plot(x, y)
            plt.title('Pixel Values for Open')
            plt.xlabel('Pixel Number')
            plt.ylabel('Average Pixel Value')
            # plt.grid(True)

            buf = io.BytesIO()
            plt.savefig(buf, format='png')
            buf.seek(0)
            plt.close()

            return send_file(buf, mimetype='image/png')
        else:
            return jsonify({"error": "Failed to download file"}), 500
    except Exception as e:
        return jsonify({"error": str(e)}), 500

@app.route('/moon_open')
def moon_open():
    file_url = request.args.get('file_url')
    if not file_url:
        return jsonify({"error": "No file URL provided"}), 400

    try:
        response = requests.get(file_url)
        if response.status_code == 200:
            file_content = response.content
            if file_url.endswith('.bz2'):
                file_content = decompress_bz2_file(file_content)
                if file_content is None:
                    return jsonify({"error": "Failed to decompress data"}), 500


            df = process_txt_file(file_content)
            df1 = df[df['Routine Code'] == 'MO']
            # routine_dict = {
            #     key: df[df['Routine Code'] == key].iloc[:, 24:]
            #     for key in df['Routine Code'].dropna().unique()
            # }
            # print(routine_dict)

            

            # Convert all object columns to int
            df1 = df1.apply(lambda col: pd.to_numeric(col, errors='coerce') if col.dtypes == 'object' else col)

            # Optional: Replace NaN values (if any) after conversion with a default value, e.g., 0
            df1 = df1.fillna(0).astype(int)

            # Ensure selected DataFrame has numeric data
            # df1.apply(pd.to_numeric)
            df1 = df1.iloc[:, 999:2030]

            # Calculate mean across rows (axis=0)
            y = df1.mean(axis=1).tolist()
            print(len(y))
            print(y)
            # Create x-axis values
            x = range(len(y))

            # Plotting logic
            plt.figure(figsize=(30, 15))
            plt.scatter(x, y)
            plt.title('Pixel Values for Moon Open')
            plt.xlabel('Pixel Number')
            plt.ylabel('Average Pixel Value')
            # plt.grid(True)

            buf = io.BytesIO()
            plt.savefig(buf, format='png')
            buf.seek(0)
            plt.close()

            return send_file(buf, mimetype='image/png')
        else:
            return jsonify({"error": "Failed to download file"}), 500
    except Exception as e:
        return jsonify({"error": str(e)}), 500

@app.route('/sun_open')
def sun_open():
    file_url = request.args.get('file_url')
    if not file_url:
        return jsonify({"error": "No file URL provided"}), 400

    try:
        response = requests.get(file_url)
        if response.status_code == 200:
            file_content = response.content
            if file_url.endswith('.bz2'):
                file_content = decompress_bz2_file(file_content)
                if file_content is None:
                    return jsonify({"error": "Failed to decompress data"}), 500

            df = process_txt_file(file_content)
            df1 = df[df['Routine Code'].isin(['SQ','SS'])]
            # routine_dict = {
            #     key: df[df['Routine Code'] == key].iloc[:, 24:]
            #     for key in df['Routine Code'].dropna().unique()
            # }
            # print(routine_dict)


            # Convert all object columns to int
            df1 = df1.apply(lambda col: pd.to_numeric(col, errors='coerce') if col.dtypes == 'object' else col)

            # Optional: Replace NaN values (if any) after conversion with a default value, e.g., 0
            df1 = df1.fillna(0).astype(int)
            timest = df1.iloc[:,1]
            # Ensure selected DataFrame has numeric data
            # df1.apply(pd.to_numeric)
            df1 = df1.iloc[:, 999:2030]


            # Calculate mean across rows (axis=0)
            y = df1.mean(axis=1).tolist()
            print(len(y))
            print(y)
            # Create x-axis values
            # x = range(len(y))


            # Plotting logic
            plt.figure(figsize=(30, 15))
            plt.scatter(timest, y)
            plt.title('Pixel Values for Sun Open')
            plt.xlabel('Pixel Number')
            plt.ylabel('Average Pixel Value')
            # plt.grid(True)

            buf = io.BytesIO()
            plt.savefig(buf, format='png')
            buf.seek(0)
            plt.close()

            return send_file(buf, mimetype='image/png')
        else:
            return jsonify({"error": "Failed to download file"}), 500
    except Exception as e:
        return jsonify({"error": str(e)}), 500

@app.route('/all_sensors')
def all_sensors():
    file_url = request.args.get('file_url')
    if not file_url:
        return jsonify({"error": "No file URL provided"}), 400

    try:
        response = requests.get(file_url)
        if response.status_code == 200:
            file_content = response.content
            if file_url.endswith('.bz2'):
                file_content = decompress_bz2_file(file_content)
                if file_content is None:
                    return jsonify({"error": "Failed to decompress data"}), 500

            df = process_txt_file(file_content)
            df1 = df.iloc[:, 1:2030]

            # Convert all object columns to int
            df1 = df1.apply(lambda col: pd.to_numeric(col, errors='coerce') if col.dtypes == 'object' else col)

            # Optional: Replace NaN values (if any) after conversion with a default value, e.g., 0
            df1 = df1.fillna(0).astype(int)
            df1['Head Sensor Pressure [hPa]'] = df1['Head Sensor Pressure [hPa]'] * 0.01

            # Plotting logic
            plt.figure(figsize=(30, 15))

            # Electronics Temperature
            plt.plot(df1['Timestamp'], df1['Electronics Temp [°C]'], label='Electronics Temp [°C]')

            # Control Temperature
            plt.plot(df1['Timestamp'], df1['Control Temp [°C]'], label='Control Temp [°C]')

            # Auxiliary Temperature
            plt.plot(df1['Timestamp'], df1['Aux Temp [°C]'], label='Aux Temp [°C]')

            # Head Sensor Temperature
            plt.plot(df1['Timestamp'], df1['Head Sensor Temp [°C]'], label='Head Sensor Temp [°C]')

            # Head Sensor Humidity
            plt.plot(df1['Timestamp'], df1['Head Sensor Humidity [%]'], label='Head Sensor Humidity [%]')

            # Head Sensor Pressure
            plt.plot(df1['Timestamp'], df1['Head Sensor Pressure [hPa]'], label='Head Sensor Pressure [hPa]')

            plt.gca().xaxis.set_major_locator(plt.MaxNLocator(40))
            plt.xlabel('Timestamp')
            plt.ylabel('Measured Values')
            plt.title('Sensor Readings Over Time')
            plt.xticks(rotation=45)
            plt.legend()
            plt.show()
            # plt.grid(True)

            buf = io.BytesIO()
            plt.savefig(buf, format='png')
            buf.seek(0)
            plt.close()

            return send_file(buf, mimetype='image/png')
        else:
            return jsonify({"error": "Failed to download file"}), 500
    except Exception as e:
        return jsonify({"error": str(e)}), 500

@app.route('/')
def home():
    return render_template('display_plot.html')


if __name__ == '__main__':
    logging.basicConfig(level=logging.DEBUG)
    app.run(debug=True)