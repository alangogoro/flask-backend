import os
import requests
import gspread
from flask import Flask, request, jsonify
from flask_cors import CORS
import hmac
import hashlib
import base64
from google.oauth2.service_account import Credentials
from dotenv import load_dotenv
import os

load_dotenv()

app = Flask(__name__)
CORS(app)

LINE_API_URL = "https://api.line.me/v2/bot/message/push"
LINE_CHANNEL_ACCESS_TOKEN = os.getenv('LINE_CHANNEL_ACCESS_TOKEN')
LINE_CHANNEL_SECRET = os.getenv('LINE_CHANNEL_SECRET')
LINE_USER_ID = os.getenv('LINE_USER_ID')

FIXED_SEASONING = {
    "spicinessOptions": ["不辣", "小辣", "中辣", "大辣"],
    "powderOptions": ["未選", "胡椒粉", "梅粉"],
    "toppingOptions": ["蔥花", "蒜粒", "洋蔥", "九層塔"]
}

@app.route('/webhook', methods=['POST'])
def webhook():
    print("收到 LINE 的 Webhook 請求！")
    try:
        # 取得 LINE 驗證簽章 (Base64)
        signature = request.headers.get('X-Line-Signature', '')
        if not signature:
            return jsonify({"success": False, "message": "Missing signature"}), 400
        
        # 取得原始請求內容（必須保留原始 bytes）
        body = request.get_data(as_text=False)
        
        # 使用 Channel Secret 計算 HMAC-SHA256
        hash_digest = hmac.new(
            LINE_CHANNEL_SECRET.encode('utf-8'),
            body,
            hashlib.sha256
        ).digest()

        # 將二進位結果轉為 Base64 字串
        calculated_signature = base64.b64encode(hash_digest).decode('utf-8')

        # 比對簽章是否相同
        if not hmac.compare_digest(calculated_signature, signature):
            print(f"[簽章不符] 計算值: {calculated_signature} vs LINE 值: {signature}")
            return jsonify({"success": False, "message": "Invalid signature"}), 403
        
        # 解析 JSON 資料
        data = request.get_json()
        print("請求內容:", data)
        
        global ADMIN_USER_ID
        
        for event in data.get('events', []):
            event_type = event.get('type')
            user_id = event.get('source', {}).get('userId')
            print(f"收到事件: {event_type}, UserID: {user_id}")
            
            # 當管理員「關注」官方帳號時，記錄 User ID
            if event_type == 'follow':
                ADMIN_USER_ID = user_id
                print(f"Admin User ID 已儲存: {ADMIN_USER_ID}")
            
            # 當管理員傳送訊息時，也可記錄 User ID（可選）
            elif event_type == 'message':
                ADMIN_USER_ID = user_id
                print(f"Admin User ID 已更新: {ADMIN_USER_ID}")
        
        return jsonify({"success": True}), 200
    except Exception as e:
        print(f"處理請求時發生錯誤: {str(e)}")
        return jsonify({"success": False, "message": "Server error"}), 500

def get_google_sheet():
    creds = Credentials.from_service_account_file('service-account.json')
    scope = ['https://www.googleapis.com/auth/spreadsheets']
    creds = creds.with_scopes(scope)
    return gspread.authorize(creds)

def format_menu_data(worksheet):
    data = worksheet.get_all_records()

    categories = {}

    for row in data:
        is_open = str(row.get('上架中', False)).lower() in ['true', '1', 'yes']
        if not is_open:
            continue

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

@app.route('/api/kuasasiaola')
def get_menu():
    try:
        gc = get_google_sheet()
        sheet = gc.open_by_key(os.getenv('SHEET_ID'))
        worksheet = sheet.sheet1

        opened = get_opened_status(worksheet)
        interval = get_prep_time(worksheet)
        
        return jsonify({
            "opened": opened,
            "categories": format_menu_data(worksheet),
            "seasoning": FIXED_SEASONING,
            "interval": interval
        })
    except Exception as e:
        return jsonify({"error": str(e)}), 500
    
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

def get_prep_time(worksheet):
    """讀取 F2 欄位的值（預設為 '0分鐘'）"""
    cell = worksheet.acell('F2').value
    # 移除「分鐘」文字並轉為整數
    return int(cell.replace('分鐘', '')) if cell else 0

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

def update_prep_time(worksheet, minutes):
    """更新 F2 欄位的值（格式為 'X分鐘'）"""
    worksheet.update_acell('F2', f'{minutes}分鐘')

@app.route('/api/setting_open', methods=['GET'])
def get_opened():
    try:
        gc = get_google_sheet()
        sheet = gc.open_by_key(os.getenv('SHEET_ID'))
        worksheet = sheet.sheet1
        
        opened_status = get_opened_status(worksheet)
        return jsonify({"opened": opened_status})
    except Exception as e:
        return jsonify({"error": str(e)}), 500

def get_opened_status(worksheet):
    cell = worksheet.acell('G2').value
    if isinstance(cell, bool):  # 處理CheckBox格式
        status = cell
    else:
        status = str(cell).strip().upper() == "TRUE" if cell else True
    return status

@app.route('/api/setting_open', methods=['POST'])
def update_opened_api():
    try:
        opened = request.json.get('opened')
        if not isinstance(opened, bool):
            return jsonify({"error": "Invalid opened value"}), 400

        gc = get_google_sheet()
        sheet = gc.open_by_key(os.getenv('SHEET_ID'))
        worksheet = sheet.sheet1
        
        update_opened_status(worksheet, opened)
        return jsonify({"success": True})
    except Exception as e:
        return jsonify({"error": str(e)}), 500

def update_opened_status(worksheet, opened):
    worksheet.update_acell('G2', f'{opened}')

@app.route('/api/send-to-line', methods=['POST'])
def send_to_line():
    try:
        data = request.json

        customer_lines = [f"名稱：{data['customer']['name']}"]
        if 'phone' in data['customer'] and data['customer']['phone']:
            customer_lines.append(f"電話：{data['customer']['phone']}")
        if 'pickupTime' in data['customer'] and data['customer']['pickupTime']:
            customer_lines.append(f"取餐時間：{data['customer']['pickupTime']}")

        seasoning_lines = [f"🌶️辣度：{data['seasoning']['spiciness']}"]
        if 'powder' in data['seasoning'] and data['seasoning']['powder'] != '未選':
            seasoning_lines.append(f"🧂粉類：{data['seasoning']['powder']}")
        if 'toppings' in data['seasoning'] and data['seasoning']['toppings']:
            seasoning_lines.append(f"✨配料：{'・'.join(data['seasoning']['toppings'])}")
        if 'notes' in data['seasoning'] and data['seasoning']['notes']:
            seasoning_lines.append('')
            seasoning_lines.append(f"📝備註：\n{data['seasoning']['notes']}")

#         order_text = f"""
# ==== 訂單內容 ====
# {'\n'.join(customer_lines)}

# {format_items(data['items'])}

# --- 調味選擇 ---
# {'\n'.join(seasoning_lines)}

# 試算金額：${data['total']}
# """.strip()

        order_text = '\n'.join([
            "==== 訂單內容 ====",
            '\n'.join(customer_lines),
            "",
            format_items(data['items']),
            "",
            "---- 調味選擇 ----",
            '\n'.join(seasoning_lines),
            "",
            f"試算金額：${data['total']}"
        ]).strip()

        # 推送 Line
        headers = {
            "Content-Type": "application/json",
            "Authorization": f"Bearer {LINE_CHANNEL_ACCESS_TOKEN}"
        }
        payload = {
            "to": f"{LINE_USER_ID}",
            "messages": [{
                "type": "text",
                "text": order_text
            }]
        }
        response = requests.post(LINE_API_URL, json=payload, headers=headers)
        response.raise_for_status()
        
        return jsonify({"success": True}), 200
    except Exception as e:
        return jsonify({"success": False, "error": str(e)}), 500

def format_items(items):
    """格式化商品明细"""
    return "\n".join([
        f"{item['name']}{' (' + item['size'] + ')' if 'size' in item else ''} x{item['quantity']}"
        for item in items
    ])

if __name__ == '__main__':
    app.run(host='0.0.0.0', port=int(os.environ.get('PORT', 10000)))