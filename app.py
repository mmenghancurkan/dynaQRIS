from flask import Flask, render_template_string, request, jsonify
from PIL import Image
import cv2
import numpy as np
import qrcode
from pyzbar.pyzbar import decode
import json
import os
import base64
from io import BytesIO
from datetime import datetime, timedelta

app = Flask(__name__)
app.config['MAX_CONTENT_LENGTH'] = 16 * 1024 * 1024

UPLOAD_FOLDER = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'uploads')
os.makedirs(UPLOAD_FOLDER, exist_ok=True)


# QRIS TLV Parser
def parse_qris_tlv(data_str):
    i = 0
    result = {}
    while i < len(data_str):
        if i + 4 > len(data_str):
            break
        tag = data_str[i:i+2]
        try:
            length = int(data_str[i+2:i+4])
            if i + 4 + length > len(data_str):
                break
            value = data_str[i+4:i+4+length]
            result[tag] = value
            i += 4 + length
        except:
            break
    return result

def parse_nested_tlv(data_str):
    i = 0
    result = {}
    while i < len(data_str):
        if i + 4 > len(data_str):
            break
        tag = data_str[i:i+2]
        try:
            length = int(data_str[i+2:i+4])
            if i + 4 + length > len(data_str):
                break
            value = data_str[i+4:i+4+length]
            result[tag] = value
            i += 4 + length
        except:
            break
    return result

def extract_merchant_info(qris_string):
    data = parse_qris_tlv(qris_string)
    info = {
        'raw_string': qris_string,
        'payload_format': data.get('00', ''),
        'point_of_initiation': data.get('01', ''),
    }
    if '26' in data:
        tag26 = parse_nested_tlv(data['26'])
        info['merchant_account'] = {
            'globally_unique_identifier': tag26.get('00', ''),
            'merchant_pan': tag26.get('01', ''),
            'merchant_id': tag26.get('02', ''),
            'merchant_criteria': tag26.get('03', ''),
        }
    if '51' in data:
        tag51 = parse_nested_tlv(data['51'])
        info['additional_merchant'] = {
            'globally_unique_identifier': tag51.get('00', ''),
            'merchant_pan': tag51.get('02', ''),
            'merchant_criteria': tag51.get('03', ''),
        }
    info['merchant_category_code'] = data.get('52', '')
    info['currency'] = data.get('53', '')
    info['amount'] = data.get('54', '')
    info['country_code'] = data.get('58', '')
    info['merchant_name'] = data.get('59', '')
    info['merchant_city'] = data.get('60', '')
    info['postal_code'] = data.get('61', '')
    if '62' in data:
        tag62 = parse_nested_tlv(data['62'])
        info['additional_data'] = {
            'bill_number': tag62.get('01', ''),
            'mobile_number': tag62.get('02', ''),
            'store_label': tag62.get('03', ''),
            'loyalty_number': tag62.get('04', ''),
            'reference_label': tag62.get('05', ''),
            'customer_label': tag62.get('06', ''),
            'terminal_label': tag62.get('07', ''),
            'purpose_of_transaction': tag62.get('08', ''),
            'additional_consumer_data': tag62.get('09', ''),
        }
    info['crc'] = data.get('63', '')
    return info

def generate_crc16(data):
    crc = 0xFFFF
    for byte in data.encode():
        crc ^= byte << 8
        for _ in range(8):
            if crc & 0x8000:
                crc = (crc << 1) ^ 0x1021
            else:
                crc <<= 1
            crc &= 0xFFFF
    return format(crc, '04X')

def generate_dynamic_qris(base_qris, amount, description=''):
    data = parse_qris_tlv(base_qris)
    if '54' in data:
        del data['54']
    if '63' in data:
        del data['63']
    amount_str = str(int(amount))
    data['54'] = amount_str
    qris_parts = []
    for tag in sorted(data.keys(), key=lambda x: int(x)):
        value = data[tag]
        qris_parts.append(f"{tag}{len(value):02d}{value}")
    qris_without_crc = ''.join(qris_parts)
    crc = generate_crc16(qris_without_crc + '6304')
    return qris_without_crc + f"6304{crc}"

def decode_qr_image(image_path):
    img = cv2.imread(image_path)
    if img is None:
        return None
    decoded_objects = decode(img)
    if decoded_objects:
        return decoded_objects[0].data.decode('utf-8')
    return None

def generate_qr_image(qris_string):
    qr = qrcode.QRCode(version=None, error_correction=qrcode.constants.ERROR_CORRECT_H, box_size=10, border=4)
    qr.add_data(qris_string)
    qr.make(fit=True)
    img = qr.make_image(fill_color="#1A1D3D", back_color="#E0E5EC")
    if img.mode != 'RGB':
        img = img.convert('RGB')
    return img

# HTML Template
HTML_TEMPLATE = """
<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>QRIS Dynamic Payment</title>
<link href="https://fonts.googleapis.com/css2?family=Poppins:wght@300;400;500;600;700&display=swap" rel="stylesheet">
<style>
*{margin:0;padding:0;box-sizing:border-box}
:root{--bg:#E0E5EC;--txt:#2D3748;--txt2:#718096;--acc:#4A5568;--ok:#48BB78;--bad:#F56565;--warn:#ED8936;--info:#4299E1;--sl:#fff;--sd:#a3b1c6}
body{font-family:'Poppins',sans-serif;background:var(--bg);min-height:100vh;color:var(--txt)}
.wrap{max-width:480px;margin:0 auto;padding:20px;min-height:100vh;display:flex;flex-direction:column}
.nf{background:var(--bg);border-radius:20px;box-shadow:9px 9px 16px var(--sd),-9px -9px 16px var(--sl)}
.np{background:var(--bg);border-radius:20px;box-shadow:inset 6px 6px 10px var(--sd),inset -6px -6px 10px var(--sl)}
.nb{background:var(--bg);border:none;border-radius:16px;padding:14px 28px;font-family:'Poppins',sans-serif;font-weight:600;font-size:14px;cursor:pointer;color:var(--txt);box-shadow:6px 6px 12px var(--sd),-6px -6px 12px var(--sl);transition:all .3s;outline:none}
.nb:hover{transform:translateY(-2px);box-shadow:8px 8px 16px var(--sd),-8px -8px 16px var(--sl)}
.nb:active{transform:translateY(0);box-shadow:inset 4px 4px 8px var(--sd),inset -4px -4px 8px var(--sl)}
.nb.p{color:#fff;background:linear-gradient(145deg,#4A5568,#2D3748)}
.nb.s{color:#fff;background:linear-gradient(145deg,#48BB78,#38A169)}
.nb.d{color:#fff;background:linear-gradient(145deg,#F56565,#E53E3E)}
.nb.i{color:#fff;background:linear-gradient(145deg,#4299E1,#3182CE)}
.nb.w{color:#fff;background:linear-gradient(145deg,#ED8936,#DD6B20)}
.ni{width:100%;padding:14px 18px;border:none;border-radius:14px;font-family:'Poppins',sans-serif;font-size:14px;color:var(--txt);background:var(--bg);box-shadow:inset 4px 4px 8px var(--sd),inset -4px -4px 8px var(--sl);outline:none;transition:all .3s}
.ni:focus{box-shadow:inset 6px 6px 12px var(--sd),inset -6px -6px 12px var(--sl)}
.ni::placeholder{color:var(--txt2)}
.hdr{text-align:center;padding:24px 0 16px}
.hdr h1{font-size:26px;font-weight:700;letter-spacing:-.5px}
.hdr p{font-size:12px;color:var(--txt2);margin-top:2px}
.bdg{display:inline-flex;align-items:center;gap:6px;margin-top:8px;padding:6px 14px;border-radius:50px;font-size:11px;font-weight:600;color:var(--txt2);background:var(--bg);box-shadow:4px 4px 8px var(--sd),-4px -4px 8px var(--sl)}
.bdg .dot{width:7px;height:7px;border-radius:50%;background:var(--ok);box-shadow:0 0 6px var(--ok);animation:pu 2s infinite}
.bdg .dot.off{background:var(--txt2);box-shadow:none;animation:none}
@keyframes pu{0%,100%{opacity:1}50%{opacity:.5}}
.sec{margin-bottom:20px;padding:20px}
.st{font-size:13px;font-weight:600;color:var(--txt2);text-transform:uppercase;letter-spacing:1px;margin-bottom:14px;display:flex;align-items:center;justify-content:space-between}
.st span{font-size:11px;color:var(--txt2);font-weight:400;text-transform:none;letter-spacing:0}
.upa{border:3px dashed #A0AEC0;border-radius:20px;padding:32px 16px;text-align:center;cursor:pointer;transition:all .3s;position:relative;overflow:hidden}
.upa:hover{border-color:var(--acc);box-shadow:inset 4px 4px 8px var(--sd),inset -4px -4px 8px var(--sl)}
.upa.drag{border-color:var(--ok);background:rgba(72,187,120,.05)}
.upi{font-size:44px;margin-bottom:10px;opacity:.6}
.upt{font-size:13px;color:var(--txt2)}
.upt strong{color:var(--txt);display:block;margin-bottom:3px;font-size:15px}
#fi{display:none}
.mc{padding:16px;margin-bottom:14px}
.mh{display:flex;align-items:center;gap:14px;margin-bottom:14px}
.ma{width:48px;height:48px;border-radius:50%;background:linear-gradient(145deg,#4A5568,#2D3748);display:flex;align-items:center;justify-content:center;font-size:20px;color:#fff;box-shadow:4px 4px 8px var(--sd),-4px -4px 8px var(--sl)}
.mi h3{font-size:16px;font-weight:600}
.mi p{font-size:12px;color:var(--txt2)}
.md{display:grid;gap:10px}
.dr{display:flex;justify-content:space-between;align-items:center;padding:8px 12px;border-radius:10px;background:var(--bg);box-shadow:inset 3px 3px 6px var(--sd),inset -3px -3px 6px var(--sl)}
.dl{font-size:11px;color:var(--txt2);font-weight:500}
.dv{font-size:12px;color:var(--txt);font-weight:600;text-align:right;max-width:60%;word-break:break-all}
.fg{margin-bottom:16px}
.fl{display:block;font-size:12px;font-weight:600;color:var(--txt2);margin-bottom:6px;padding-left:4px}
.aiw{position:relative}
.cs{position:absolute;left:18px;top:50%;transform:translateY(-50%);font-weight:600;color:var(--txt2);font-size:14px}
.ai{padding-left:48px!important;font-size:18px!important;font-weight:700!important}
.qa{display:flex;gap:8px;margin-top:10px;flex-wrap:wrap}
.qa button{padding:7px 14px;border-radius:10px;font-size:12px;font-weight:600;color:var(--txt2);background:var(--bg);border:none;cursor:pointer;box-shadow:4px 4px 8px var(--sd),-4px -4px 8px var(--sl);transition:all .2s}
.qa button:hover{transform:translateY(-1px);color:var(--txt)}
.qa button:active{box-shadow:inset 2px 2px 4px var(--sd),inset -2px -2px 4px var(--sl)}
.qr{text-align:center;padding:20px}
.qic{display:inline-block;padding:16px;border-radius:20px;margin-bottom:16px;background:#fff;box-shadow:8px 8px 16px var(--sd),-8px -8px 16px var(--sl)}
.qic img{width:220px;height:220px;border-radius:10px;display:block}
.oi{margin-bottom:16px}
.oa{font-size:28px;font-weight:700;margin-bottom:3px}
.oid{font-size:11px;color:var(--txt2);font-family:monospace}
.et{display:inline-flex;align-items:center;gap:5px;padding:7px 14px;border-radius:50px;font-size:12px;font-weight:600;color:var(--warn);background:var(--bg);box-shadow:inset 3px 3px 6px var(--sd),inset -3px -3px 6px var(--sl);margin-top:10px}
.mo{position:fixed;top:0;left:0;right:0;bottom:0;background:rgba(224,229,236,.92);backdrop-filter:blur(10px);display:flex;align-items:center;justify-content:center;z-index:1000;opacity:0;visibility:hidden;transition:all .3s;padding:20px}
.mo.a{opacity:1;visibility:visible}
.moc{width:100%;max-width:420px;max-height:90vh;overflow-y:auto;transform:scale(.9) translateY(20px);transition:all .3s}
.mo.a .moc{transform:scale(1) translateY(0)}
.moh{text-align:center;margin-bottom:16px}
.moh h2{font-size:18px;font-weight:700}
.moh p{font-size:12px;color:var(--txt2);margin-top:3px}
.moa{display:flex;gap:10px;margin-top:20px}
.moa .nb{flex:1}
.toast{position:fixed;bottom:24px;left:50%;transform:translateX(-50%) translateY(100px);padding:12px 24px;border-radius:14px;font-size:13px;font-weight:600;color:#fff;z-index:2000;opacity:0;transition:all .4s cubic-bezier(.68,-.55,.265,1.55);box-shadow:6px 6px 12px var(--sd),-6px -6px 12px var(--sl)}
.toast.sh{transform:translateX(-50%) translateY(0);opacity:1}
.toast.su{background:var(--ok)}.toast.er{background:var(--bad)}.toast.in{background:var(--acc)}
.sp{width:36px;height:36px;border:3px solid var(--bg);border-top-color:var(--acc);border-radius:50%;animation:sp .8s linear infinite;margin:16px auto;box-shadow:0 0 0 3px var(--sl),0 0 0 6px var(--sd)}
@keyframes sp{to{transform:rotate(360deg)}}
.hid{display:none!important}
::-webkit-scrollbar{width:5px}
::-webkit-scrollbar-track{background:transparent}
::-webkit-scrollbar-thumb{background:#A0AEC0;border-radius:3px}
.su{animation:su .4s ease forwards}
@keyframes su{from{opacity:0;transform:translateY(30px)}to{opacity:1;transform:translateY(0)}}
.pgrid{display:grid;gap:10px}
.pcard{display:flex;align-items:center;gap:12px;padding:14px;border-radius:14px;background:var(--bg);box-shadow:5px 5px 10px var(--sd),-5px -5px 10px var(--sl);cursor:pointer;transition:all .25s;position:relative}
.pcard:hover{transform:translateY(-2px);box-shadow:7px 7px 14px var(--sd),-7px -7px 14px var(--sl)}
.pcard:active{box-shadow:inset 3px 3px 6px var(--sd),inset -3px -3px 6px var(--sl)}
.pcard .pava{width:44px;height:44px;border-radius:12px;background:linear-gradient(145deg,#4A5568,#2D3748);display:flex;align-items:center;justify-content:center;font-size:18px;color:#fff;box-shadow:3px 3px 6px var(--sd),-3px -3px 6px var(--sl);flex-shrink:0}
.pcard .pinfo{flex:1;min-width:0}
.pcard .pinfo h4{font-size:14px;font-weight:600;color:var(--txt);white-space:nowrap;overflow:hidden;text-overflow:ellipsis}
.pcard .pinfo p{font-size:11px;color:var(--txt2);margin-top:1px}
.pcard .pdel{width:32px;height:32px;border-radius:8px;display:flex;align-items:center;justify-content:center;font-size:14px;color:var(--bad);background:var(--bg);border:none;cursor:pointer;box-shadow:3px 3px 6px var(--sd),-3px -3px 6px var(--sl);flex-shrink:0;transition:all .2s}
.pcard .pdel:hover{box-shadow:inset 2px 2px 4px var(--sd),inset -2px -2px 4px var(--sl)}
.pcard .pdel:active{transform:scale(.95)}
.pnew{display:flex;align-items:center;justify-content:center;gap:8px;padding:14px;border-radius:14px;background:var(--bg);border:2px dashed #A0AEC0;cursor:pointer;transition:all .25s;color:var(--txt2);font-weight:600;font-size:13px}
.pnew:hover{border-color:var(--acc);color:var(--txt);box-shadow:inset 3px 3px 6px var(--sd),inset -3px -3px 6px var(--sl)}
.pnew:active{transform:scale(.98)}
.empty{text-align:center;padding:32px 16px;color:var(--txt2)}
.empty .eicon{font-size:44px;margin-bottom:10px;opacity:.5}
.empty p{font-size:13px}
.hist-btn{position:fixed;bottom:20px;right:20px;width:48px;height:48px;border-radius:50%;background:linear-gradient(145deg,#4A5568,#2D3748);color:#fff;border:none;cursor:pointer;box-shadow:5px 5px 10px var(--sd),-5px -5px 10px var(--sl);font-size:20px;z-index:50;transition:all .3s;display:flex;align-items:center;justify-content:center}
.hist-btn:hover{transform:scale(1.1)}
.hist-btn:active{transform:scale(0.95);box-shadow:inset 3px 3px 6px rgba(0,0,0,.3),inset -3px -3px 6px rgba(255,255,255,.1)}
.hcard{display:flex;align-items:center;gap:12px;padding:14px;border-radius:14px;background:var(--bg);box-shadow:5px 5px 10px var(--sd),-5px -5px 10px var(--sl);margin-bottom:10px;transition:all .25s}
.hcard:hover{transform:translateY(-2px);box-shadow:7px 7px 14px var(--sd),-7px -7px 14px var(--sl)}
.hinfo{flex:1;min-width:0}
.hinfo h4{font-size:14px;font-weight:600;color:var(--txt);white-space:nowrap;overflow:hidden;text-overflow:ellipsis}
.hinfo p{font-size:11px;color:var(--txt2);margin-top:2px}
.hmeta{display:flex;align-items:center;gap:8px;flex-shrink:0}
.hamt{font-size:14px;font-weight:700;color:var(--txt)}
.sb{display:inline-flex;align-items:center;gap:4px;padding:4px 10px;border-radius:50px;font-size:10px;font-weight:700;text-transform:uppercase;letter-spacing:.5px}
.sb.pen{color:#B7791F;background:rgba(237,137,54,.12)}
.sb.paid{color:#276749;background:rgba(72,187,120,.15)}
.sb.can{color:#C53030;background:rgba(245,101,101,.12)}
.sb.exp{color:#718096;background:rgba(113,128,150,.12)}
.ss{display:flex;gap:6px;margin-top:12px;flex-wrap:wrap;justify-content:center}
.ssb{padding:6px 14px;border-radius:50px;border:none;font-family:'Poppins',sans-serif;font-size:11px;font-weight:600;cursor:pointer;transition:all .2s;box-shadow:3px 3px 6px var(--sd),-3px -3px 6px var(--sl)}
.ssb:hover{transform:translateY(-1px)}
.ssb:active{box-shadow:inset 2px 2px 4px var(--sd),inset -2px -2px 4px var(--sl)}
.ssb.on{box-shadow:inset 2px 2px 4px var(--sd),inset -2px -2px 4px var(--sl)}
.ssb.pen{color:#B7791F;background:var(--bg)}
.ssb.paid{color:#276749;background:var(--bg)}
.ssb.can{color:#C53030;background:var(--bg)}
.ssb.exp{color:#718096;background:var(--bg)}
.hback{width:100%;margin-top:10px;font-size:12px}
</style>
</head>
<body>

<div class="wrap">
  <div class="hdr">
    <h1>QRIS Dynamic</h1>
    <p>Automated Payment Generator</p>
    <div class="bdg"><span class="dot" id="bdot"></span><span id="st">No Profile Selected</span></div>
  </div>

  <div id="sec-prof" class="sec nf">
    <div class="st">Select QRIS Profile <span>or create a new one</span></div>
    <div class="pgrid" id="plist"></div>
    <div class="pnew" id="pnew" style="margin-top:10px"><span style="font-size:18px">+</span> Create New Profile</div>
  </div>

  <div id="sec-up" class="sec nf hid">
    <div class="st">Upload Static QRIS</div>
    <div class="upa" id="upa"><div class="upi">📷</div><div class="upt"><strong>Upload your static QRIS</strong>Drag & drop or click to browse</div></div>
    <input type="file" id="fi" accept="image/*">
    <button class="nb" id="bback1" style="width:100%;margin-top:14px;font-size:12px">← Back to Profiles</button>
  </div>

  <div id="sec-mc" class="sec nf hid">
    <div class="st">Confirm & Name Your Profile</div>
    <div class="mc np">
      <div class="mh"><div class="ma">🏪</div><div class="mi"><h3 id="cmn">-</h3><p id="cmc">-</p></div></div>
      <div class="md" id="md"></div>
    </div>
    <div class="fg" style="margin-top:14px">
      <label class="fl">Profile Name</label>
      <input type="text" class="ni" id="pname" placeholder="e.g. My Store, Warung Pak Budi">
    </div>
    <div class="moa">
      <button class="nb" id="bcu">Cancel</button>
      <button class="nb s" id="bcm">✓ Save Profile</button>
    </div>
  </div>

  <div id="sec-pay" class="sec nf hid">
    <div class="st">Generate Payment</div>
    <div class="mc np" style="margin-bottom:16px">
      <div class="mh"><div class="ma">🏪</div><div class="mi"><h3 id="smn">-</h3><p id="smc">-</p></div></div>
    </div>
    <div class="fg">
      <label class="fl">Amount (IDR)</label>
      <div class="aiw"><span class="cs">Rp</span><input type="number" class="ni ai" id="amt" placeholder="0" min="1000" max="10000000" step="1000"></div>
      <div class="qa">
        <button data-a="10000">10K</button><button data-a="20000">20K</button><button data-a="50000">50K</button>
        <button data-a="100000">100K</button><button data-a="200000">200K</button><button data-a="500000">500K</button>
      </div>
    </div>
    <div class="fg">
      <label class="fl">Description (Optional)</label>
      <input type="text" class="ni" id="desc" placeholder="e.g. Invoice #123">
    </div>
    <button class="nb p" id="bgen" style="width:100%">Generate QRIS Payment</button>
    <div style="display:flex;gap:8px;margin-top:10px">
      <button class="nb" id="bswitch" style="flex:1;font-size:12px">Switch Profile</button>
      <button class="nb d" id="brst" style="flex:1;font-size:12px">Delete Profile</button>
    </div>
  </div>

  <div id="sec-res" class="sec nf hid">
    <div class="st">Payment QR Code</div>
    <div class="qr">
      <div class="qic"><img id="rqr" src="" alt="QRIS"></div>
      <div class="oi"><div class="oa" id="ramt">Rp 0</div><div class="oid" id="roid">-</div></div>
      <div class="et">⏱ Expires at <span id="rexp">--:--</span></div>
      <div class="ss" id="stat-ctrl">
        <button class="ssb pen on" data-st="Pending">Pending</button>
        <button class="ssb paid" data-st="Paid">Paid</button>
        <button class="ssb can" data-st="Cancelled">Cancelled</button>
        <button class="ssb exp" data-st="Expired">Expired</button>
      </div>
      <div style="margin-top:16px"><button class="nb" id="bdn" style="margin-right:6px">⬇ Download</button><button class="nb p" id="bnew">New Payment</button></div>
      <div style="margin-top:10px"><button class="nb i" id="bhist-res" style="width:100%;font-size:12px">📜 View History</button></div>
    </div>
  </div>

  <div id="sec-hist" class="sec nf hid">
    <div class="st">Transaction History <span>past payments</span></div>
    <div id="hlist"></div>
    <button class="nb hback" id="bback-hist">← Back</button>
  </div>
</div>

<button class="hist-btn" id="bhist" title="Transaction History">📜</button>


<div class="mo" id="ldm"><div class="moc" style="text-align:center"><div class="sp"></div><p style="margin-top:14px;color:var(--txt2);font-weight:500;font-size:13px">Processing...</p></div></div>
<div class="toast" id="toast"></div>

<script>
const LS_KEY = 'qris_profiles_v1';
const HIST_KEY = 'qris_history_v1';
let profiles = [], activeProfileId = null, tempQrisString = null, tempMerchantInfo = null, history = [], lastOrderId = null;
const $ = id => document.getElementById(id);
const secProf = $('sec-prof'), secUp = $('sec-up'), secMc = $('sec-mc'), secPay = $('sec-pay'), secRes = $('sec-res'), secHist = $('sec-hist');
const ldm = $('ldm'), toast = $('toast'), st = $('st'), bdot = $('bdot');

function sh(msg, t='in') { toast.textContent = msg; toast.className = 'toast ' + t; toast.classList.add('sh'); setTimeout(() => toast.classList.remove('sh'), 3000); }
function fr(a) { return 'Rp ' + parseInt(a).toLocaleString('id-ID'); }
function sl() { ldm.classList.add('a'); }
function hl() { ldm.classList.remove('a'); }
function uid() { return Date.now().toString(36) + Math.random().toString(36).slice(2,6); }
function esc(s) { const d = document.createElement('div'); d.textContent = s; return d.innerHTML; }
function showModal(m) { m.classList.add('a'); }
function hideModal(m) { m.classList.remove('a'); }

function loadProfiles() { try { const raw = localStorage.getItem(LS_KEY); profiles = raw ? JSON.parse(raw) : []; } catch(e) { profiles = []; } }
function saveProfiles() { localStorage.setItem(LS_KEY, JSON.stringify(profiles)); }

function renderProfiles() {
  const list = $('plist');
  list.innerHTML = '';
  if (profiles.length === 0) { list.innerHTML = '<div class="empty"><div class="eicon">📭</div><p>No profiles yet.<br>Create your first QRIS profile below.</p></div>'; return; }
  profiles.forEach(p => {
    const card = document.createElement('div');
    card.className = 'pcard';
    card.innerHTML = '<div class="pava">🏪</div><div class="pinfo"><h4>'+esc(p.name)+'</h4><p>'+esc(p.merchant_name||'Unknown')+' · '+esc(p.merchant_city||'-')+'</p></div><button class="pdel" data-id="'+p.id+'" title="Delete">🗑</button>';
    card.addEventListener('click', (e) => { if (e.target.classList.contains('pdel')) { e.stopPropagation(); deleteProfile(p.id); } else { selectProfile(p.id); } });
    list.appendChild(card);
  });
}

function deleteProfile(id) {
  if (!confirm('Delete this profile?')) return;
  profiles = profiles.filter(p => p.id !== id);
  saveProfiles();
  renderProfiles();
  if (activeProfileId === id) { activeProfileId = null; updateHeader(); }
  sh('Profile deleted', 'in');
}

function selectProfile(id) {
  activeProfileId = id;
  const p = profiles.find(x => x.id === id);
  if (!p) return;
  updateHeader();
  secProf.classList.add('hid');
  secPay.classList.remove('hid');
  secPay.classList.add('su');
  $('smn').textContent = p.merchant_name || 'Unknown';
  $('smc').textContent = p.merchant_city || '';
  sh('Profile loaded: ' + p.name, 'su');
}

function updateHeader() {
  const p = profiles.find(x => x.id === activeProfileId);
  if (p) { st.textContent = 'Ready'; bdot.classList.remove('off'); }
  else { st.textContent = 'No Profile Selected'; bdot.classList.add('off'); }
}

function loadHistory() { try { const raw = localStorage.getItem(HIST_KEY); history = raw ? JSON.parse(raw) : []; } catch(e) { history = []; } }
function saveHistory() { localStorage.setItem(HIST_KEY, JSON.stringify(history)); }
function addTransaction(data) {
  history.unshift({
    order_id: data.order_id, amount: data.amount, description: data.description || '',
    merchant_name: data.merchant_name || 'Merchant', created_at: new Date().toISOString(),
    expiry: data.expiry, status: 'Pending'
  });
  saveHistory();
}
function updateTransactionStatus(orderId, status) {
  const tx = history.find(h => h.order_id === orderId);
  if (tx) { tx.status = status; saveHistory(); return true; }
  return false;
}
function getStatusClass(st) {
  if (st === 'Paid') return 'paid';
  if (st === 'Cancelled') return 'can';
  if (st === 'Expired') return 'exp';
  return 'pen';
}
function renderHistory() {
  const list = $('hlist');
  list.innerHTML = '';
  if (history.length === 0) { list.innerHTML = '<div class="empty"><div class="eicon">📭</div><p>No transactions yet.<br>Generate a QRIS payment to see history.</p></div>'; return; }
  history.forEach(h => {
    const sc = getStatusClass(h.status);
    const card = document.createElement('div');
    card.className = 'hcard';
    card.innerHTML = '<div class="hinfo"><h4>'+esc(h.merchant_name)+'</h4><p>'+esc(h.order_id)+' · '+new Date(h.created_at).toLocaleString('id-ID')+'</p></div><div class="hmeta"><div class="hamt">'+fr(h.amount)+'</div><select class="sb '+sc+'" data-oid="'+esc(h.order_id)+'" style="border:none;cursor:pointer;font-family:Poppins,sans-serif;font-size:10px;font-weight:700"><option value="Pending" '+(h.status==='Pending'?'selected':'')+'>Pending</option><option value="Paid" '+(h.status==='Paid'?'selected':'')+'>Paid</option><option value="Cancelled" '+(h.status==='Cancelled'?'selected':'')+'>Cancelled</option><option value="Expired" '+(h.status==='Expired'?'selected':'')+'>Expired</option></select></div>';
    list.appendChild(card);
  });
  list.querySelectorAll('select[data-oid]').forEach(sel => {
    sel.addEventListener('change', (e) => {
      updateTransactionStatus(e.target.dataset.oid, e.target.value);
      renderHistory();
      sh('Status updated: ' + e.target.value, 'su');
    });
  });
}

function setStatusUI(status) {
  document.querySelectorAll('#stat-ctrl .ssb').forEach(b => b.classList.toggle('on', b.dataset.st === status));
}

const upa = $('upa'), fi = $('fi');
upa.addEventListener('click', () => fi.click());
upa.addEventListener('dragover', e => { e.preventDefault(); upa.classList.add('drag'); });
upa.addEventListener('dragleave', () => upa.classList.remove('drag'));
upa.addEventListener('drop', e => { e.preventDefault(); upa.classList.remove('drag'); if (e.dataTransfer.files.length) handleFile(e.dataTransfer.files[0]); });
fi.addEventListener('change', e => { if (e.target.files.length) handleFile(e.target.files[0]); });

async function handleFile(f) {
  if (!f.type.startsWith('image/')) { sh('Please upload an image', 'er'); return; }
  sl();
  const fd = new FormData();
  fd.append('qr_image', f);
  try {
    const r = await fetch('/upload', { method: 'POST', body: fd });
    const d = await r.json();
    if (d.success) {
      tempQrisString = d.merchant_info.raw_string;
      tempMerchantInfo = d.merchant_info;
      displayMerchantForConfirmation(d.merchant_info);
      secUp.classList.add('hid');
      secMc.classList.remove('hid');
      secMc.classList.add('su');
    } else { sh(d.error || 'Failed to decode QR', 'er'); }
  } catch(e) { sh('Network error', 'er'); }
  finally { hl(); }
}

function displayMerchantForConfirmation(info) {
  $('cmn').textContent = info.merchant_name || 'Unknown Merchant';
  $('cmc').textContent = info.merchant_city || 'Unknown Location';
  const c = $('md');
  c.innerHTML = '';
  const fs = [
    {l:'Merchant Name', v:info.merchant_name}, {l:'City', v:info.merchant_city},
    {l:'Country', v:info.country_code}, {l:'Currency', v:info.currency==='360'?'IDR (360)':info.currency},
    {l:'MCC', v:info.merchant_category_code}, {l:'Postal Code', v:info.postal_code}
  ];
  if (info.merchant_account) { fs.push({l:'Merchant ID', v:info.merchant_account.merchant_id}); fs.push({l:'Merchant PAN', v:info.merchant_account.merchant_pan}); }
  if (info.additional_data && info.additional_data.terminal_label) fs.push({l:'Terminal', v:info.additional_data.terminal_label});
  fs.forEach(f => { if (f.v) { const r = document.createElement('div'); r.className='dr'; r.innerHTML='<span class="dl">'+f.l+'</span><span class="dv">'+f.v+'</span>'; c.appendChild(r); } });
}

$('bcu').addEventListener('click', () => { secMc.classList.add('hid'); secUp.classList.remove('hid'); tempQrisString = null; tempMerchantInfo = null; });

$('bcm').addEventListener('click', async () => {
  const name = $('pname').value.trim();
  if (!name) { sh('Please enter a profile name', 'er'); return; }
  if (!tempQrisString) return;
  if (profiles.some(p => p.name.toLowerCase() === name.toLowerCase())) { sh('Profile name already exists', 'er'); return; }
  const newProfile = {
    id: uid(), name: name, qris_string: tempQrisString,
    merchant_name: tempMerchantInfo.merchant_name || '', merchant_city: tempMerchantInfo.merchant_city || '',
    country_code: tempMerchantInfo.country_code || '', currency: tempMerchantInfo.currency || '',
    merchant_category_code: tempMerchantInfo.merchant_category_code || '', postal_code: tempMerchantInfo.postal_code || '',
    merchant_id: tempMerchantInfo.merchant_account?.merchant_id || '', merchant_pan: tempMerchantInfo.merchant_account?.merchant_pan || '',
    terminal_label: tempMerchantInfo.additional_data?.terminal_label || '', created_at: new Date().toISOString()
  };
  profiles.push(newProfile);
  saveProfiles();
  tempQrisString = null; tempMerchantInfo = null; $('pname').value = '';
  secMc.classList.add('hid'); secProf.classList.remove('hid'); secProf.classList.add('su');
  renderProfiles();
  sh('Profile "' + name + '" saved!', 'su');
});

$('pnew').addEventListener('click', () => { secProf.classList.add('hid'); secUp.classList.remove('hid'); secUp.classList.add('su'); });
$('bback1').addEventListener('click', () => { secUp.classList.add('hid'); secProf.classList.remove('hid'); secProf.classList.add('su'); });
$('bswitch').addEventListener('click', () => { secPay.classList.add('hid'); secProf.classList.remove('hid'); secProf.classList.add('su'); activeProfileId = null; updateHeader(); });
$('brst').addEventListener('click', () => {
  if (!activeProfileId) return;
  const p = profiles.find(x => x.id === activeProfileId);
  if (!confirm('Delete profile "' + (p?.name || '') + '"?')) return;
  profiles = profiles.filter(x => x.id !== activeProfileId);
  saveProfiles(); activeProfileId = null;
  secPay.classList.add('hid'); secProf.classList.remove('hid'); secProf.classList.add('su');
  renderProfiles(); updateHeader(); sh('Profile deleted', 'in');
});

$('bgen').addEventListener('click', async () => {
  const a = $('amt').value, dc = $('desc').value;
  if (!a || a < 1000) { sh('Min amount Rp 1,000', 'er'); return; }
  const prof = profiles.find(x => x.id === activeProfileId);
  if (!prof) { sh('No active profile', 'er'); return; }
  sl();
  try {
    const r = await fetch('/generate', {
      method: 'POST',
      headers: {'Content-Type': 'application/json'},
      body: JSON.stringify({ amount: parseInt(a), description: dc, qris_string: prof.qris_string, merchant_name: prof.merchant_name })
    });
    const d = await r.json();
    if (d.success) {
      lastOrderId = d.order_id;
      addTransaction({ order_id: d.order_id, amount: d.amount, description: d.description, merchant_name: prof.merchant_name, expiry: d.expiry });
      $('rqr').src = d.qr_image; $('ramt').textContent = fr(d.amount); $('roid').textContent = d.order_id; $('rexp').textContent = d.expiry;
      setStatusUI('Pending');
      secPay.classList.add('hid'); secRes.classList.remove('hid'); secRes.classList.add('su'); sh('QRIS generated!', 'su');
    } else sh(d.error || 'Failed', 'er');
  } catch(e) { sh('Network error', 'er'); }
  finally { hl(); }
});

$('bnew').addEventListener('click', () => { secRes.classList.add('hid'); secPay.classList.remove('hid'); $('amt').value = ''; $('desc').value = ''; });
$('bdn').addEventListener('click', () => { const l = document.createElement('a'); l.href = $('rqr').src; l.download = 'qris-' + Date.now() + '.png'; l.click(); sh('Downloaded!', 'su'); });
document.querySelectorAll('.qa button').forEach(b => b.addEventListener('click', () => $('amt').value = b.dataset.a));

document.querySelectorAll('#stat-ctrl .ssb').forEach(b => b.addEventListener('click', () => {
  if (!lastOrderId) return;
  updateTransactionStatus(lastOrderId, b.dataset.st);
  setStatusUI(b.dataset.st);
  sh('Status set: ' + b.dataset.st, 'su');
}));

$('bhist').addEventListener('click', () => { renderHistory(); [secProf, secUp, secMc, secPay, secRes].forEach(s => s.classList.add('hid')); secHist.classList.remove('hid'); secHist.classList.add('su'); });
$('bhist-res').addEventListener('click', () => { renderHistory(); secRes.classList.add('hid'); secHist.classList.remove('hid'); secHist.classList.add('su'); });
$('bback-hist').addEventListener('click', () => { secHist.classList.add('hid'); secProf.classList.remove('hid'); secProf.classList.add('su'); });

loadProfiles();
loadHistory();
renderProfiles();
updateHeader();
</script>
</body>
</html>
"""

# Routes
@app.route('/')
def index():
    return render_template_string(HTML_TEMPLATE)

@app.route('/upload', methods=['POST'])
def upload_qr():
    if 'qr_image' not in request.files:
        return jsonify({'success': False, 'error': 'No file uploaded'}), 400
    file = request.files['qr_image']
    if file.filename == '':
        return jsonify({'success': False, 'error': 'No file selected'}), 400
    filename = f"up_{datetime.now().strftime('%Y%m%d%H%M%S')}_{os.urandom(4).hex()}.png"
    filepath = os.path.join(UPLOAD_FOLDER, filename)
    file.save(filepath)
    qris_string = decode_qr_image(filepath)
    if not qris_string:
        os.remove(filepath)
        return jsonify({'success': False, 'error': 'Could not decode QR code'}), 400
    merchant_info = extract_merchant_info(qris_string)
    return jsonify({'success': True, 'merchant_info': merchant_info})

@app.route('/generate', methods=['POST'])
def generate_payment():
    data = request.get_json()
    amount = data.get('amount')
    description = data.get('description', '')
    qris_string = data.get('qris_string')
    merchant_name = data.get('merchant_name', 'Merchant')

    if not qris_string:
        return jsonify({'success': False, 'error': 'No QRIS string provided'}), 400
    if not amount:
        return jsonify({'success': False, 'error': 'Amount required'}), 400
    try:
        amount = int(amount)
        if amount < 1000:
            return jsonify({'success': False, 'error': 'Min Rp 1,000'}), 400
        if amount > 10000000:
            return jsonify({'success': False, 'error': 'Max Rp 10,000,000'}), 400
    except ValueError:
        return jsonify({'success': False, 'error': 'Invalid amount'}), 400

    dynamic_qris = generate_dynamic_qris(qris_string, amount, description)
    qr_img = generate_qr_image(dynamic_qris)
    img_buffer = BytesIO()
    qr_img.save(img_buffer, format='PNG')
    img_buffer.seek(0)
    img_base64 = base64.b64encode(img_buffer.getvalue()).decode()
    order_id = f"ORD-{datetime.now().strftime('%Y%m%d%H%M%S')}-{os.urandom(3).hex().upper()}"
    expiry = datetime.now() + timedelta(minutes=15)

    return jsonify({
        'success': True, 'order_id': order_id, 'amount': amount,
        'description': description, 'qr_image': f"data:image/png;base64,{img_base64}",
        'qris_string': dynamic_qris, 'expiry': expiry.strftime('%H:%M'),
    })

if __name__ == '__main__':
    app.run(debug=True, host='0.0.0.0', port=5000)
