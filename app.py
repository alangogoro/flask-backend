import os
import requests
import gspread
from flask import Flask, request, jsonify
from flask_cors import CORS
from google.oauth2.service_account import Credentials
from dotenv import load_dotenv

load_dotenv()

app = Flask(__name__)
CORS(app)

LINE_API_URL = "https://api.line.me/v2/bot/message/push"
LINE_CHANNEL_ACCESS_TOKEN = os.getenv('LINE_CHANNEL_ACCESS_TOKEN')
LINE_USER_ID = os.getenv('LINE_USER_ID')

FIXED_SEASONING = {
    "spicinessOptions": ["不辣", "小辣", "中辣", "大辣"],
    "powderOptions": ["未選", "胡椒粉", "梅粉"],
    "toppingOptions": ["蔥花", "蒜粒", "洋蔥", "九層塔"]
}

def get_google_sheet():
    creds = Credentials.from_service_account_file('service-account.json')
    scope = ['https://www.googleapis.com/auth/spreadsheets']
    creds = creds.with_scopes(scope)
    return gspread.authorize(creds)

def format_menu_data(worksheet):
    data = worksheet.get_all_records()
    categories = {}

    for row in data:
        category_name = row['分類']
        if category_name not in categories:
            categories[category_name] = {
                "name": category_name,
                "items": []
            }

        item = {
            "name": row['品名'],
            "price": int(row['價格']),
            "quantity": 0
        }

        if row['規格'] and '/' in row['規格']:
            sizes = []
            for size in row['規格'].split('/'):
                label, price = size.split(':')
                sizes.append({
                    "label": label.strip(),
                    "price": int(price.strip())
                })
            item["sizes"] = sizes
            item["selectedSize"] = 0

        categories[category_name]['items'].append(item)

    return list(categories.values())

@app.route('/webhook', methods=['POST'])
def webhook():
    return jsonify({"success": True}), 200

@app.route('/api/kuasasiaola')
def get_menu():
    try:
        gc = get_google_sheet()
        sheet = gc.open_by_key(os.getenv('SHEET_ID'))
        worksheet = sheet.sheet1
        
        return jsonify({
            "categories": format_menu_data(worksheet),
            "seasoning": FIXED_SEASONING
        })
    except Exception as e:
        return jsonify({"error": str(e)}), 500
    
# 新增以下函數來讀取和更新 F2 欄位
def get_prep_time(worksheet):
    """讀取 F2 欄位的值（預設為 '0分鐘'）"""
    cell = worksheet.acell('F2').value
    # 移除「分鐘」文字並轉為整數
    return int(cell.replace('分鐘', '')) if cell else 0

def update_prep_time(worksheet, minutes):
    """更新 F2 欄位的值（格式為 'X分鐘'）"""
    worksheet.update_acell('F2', f'{minutes}分鐘')

@app.route('/api/setting_time', methods=['GET'])
def get_prep_time_api():
    try:
        gc = get_google_sheet()
        sheet = gc.open_by_key(os.getenv('SHEET_ID'))
        worksheet = sheet.sheet1
        
        current_time = get_prep_time(worksheet)
        return jsonify({"interval": current_time})
    except Exception as e:
        return jsonify({"error": str(e)}), 500

@app.route('/api/setting_time', methods=['POST'])
def update_prep_time_api():
    try:
        minutes = request.json.get('interval')
        if not isinstance(minutes, int) or minutes < 0:
            return jsonify({"error": "Invalid interval value"}), 400

        gc = get_google_sheet()
        sheet = gc.open_by_key(os.getenv('SHEET_ID'))
        worksheet = sheet.sheet1
        
        update_prep_time(worksheet, minutes)
        return jsonify({"success": True})
    except Exception as e:
        return jsonify({"error": str(e)}), 500

@app.route('/api/send-to-line', methods=['POST'])
def send_to_line():
    try:
        data = request.json
        order_text = data.get('order')
        
        headers = {
            "Content-Type": "application/json",
            "Authorization": f"Bearer {LINE_CHANNEL_ACCESS_TOKEN}"
        }
        payload = {
            "to": LINE_USER_ID,
            "messages": [{"type": "text", "text": order_text}]
        }
        response = requests.post(LINE_API_URL, json=payload, headers=headers)
        response.raise_for_status()
        
        return jsonify({"success": True}), 200
    except Exception as e:
        return jsonify({"success": False, "error": str(e)}), 500

if __name__ == '__main__':
    app.run(host='0.0.0.0', port=int(os.environ.get('PORT', 10000)))