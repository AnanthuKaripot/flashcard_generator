import os
import random
import json
import time
import textwrap
import re
import base64
import numpy as np
from PIL import Image, ImageDraw, ImageFont, ImageFilter, ImageEnhance

# --- CONFIGURATION ---
SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
PARENT_DIR = os.path.dirname(SCRIPT_DIR) # tools root
ASSETS_DIR = os.path.join(SCRIPT_DIR, "assets")
LOGO_PATH = os.path.join(ASSETS_DIR, "logo.png")

# Output directory for images
# Output directory for images
# Uses user's home directory to be generic and git-friendly
OUTPUT_DIR = os.path.join(os.path.expanduser("~"), ".n8n-files", "flashcards")
WEB_DIR = os.path.join(SCRIPT_DIR, "web_app")

# Path to the curated flashcards JSON
FLASHCARDS_JSON_PATH = os.path.join(PARENT_DIR, "neetpg_app", "assets", "flashcards.json")
HISTORY_FILE = os.path.join(OUTPUT_DIR, "flashcard_history.json")
BATCH_SIZE = 5

# Theme: "Midnight Prism" - High Contrast, Premium
BG_TOP = (13, 13, 22)       # Deepest Indigo
BG_BOTTOM = (5, 5, 10)      # Almost Black
ACCENT_CYAN = (6, 182, 212) # Cyan 500
ACCENT_GOLD = (245, 158, 11) # Amber 500
ACCENT_GREEN = (16, 185, 129) # Emerald 500
TEXT_MAIN = (248, 250, 252) # Slate 50
TEXT_MUTED = (148, 163, 184) # Slate 400

W, H = 1080, 1350
PADDING = 80

# --- SETUP ---
if not os.path.exists(OUTPUT_DIR):
    os.makedirs(OUTPUT_DIR)

# --- DATABASE & LOGIC ---

def load_history():
    if not os.path.exists(HISTORY_FILE): return []
    try:
        with open(HISTORY_FILE, 'r') as f: return json.load(f)
    except: return []

def save_history_entry(q_id):
    history = load_history()
    if q_id not in history:
        history.append(q_id)
        with open(HISTORY_FILE, 'w') as f: json.dump(history, f)

def fetch_batch_questions(count=5):
    if not os.path.exists(FLASHCARDS_JSON_PATH):
        print(f"Error: Flashcards JSON not found at {FLASHCARDS_JSON_PATH}")
        return []
        
    with open(FLASHCARDS_JSON_PATH, 'r', encoding='utf-8') as f:
        all_cards = json.load(f)
        
    used_ids = load_history()
    
    available = [
        c for c in all_cards 
        if c['id'] not in used_ids 
        and (not c.get('image')) 
        # Relaxed length constraint for PIL wrapping
        and len(c.get('explanation', '')) < 600
    ]
    
    if len(available) < count:
        print("Warning: Low on fresh cards. Using any unused non-image cards.")
        available = [
            c for c in all_cards 
            if c['id'] not in used_ids 
            and (not c.get('image'))
        ]
        
    if not available:
        print("Progress: Resetting history to reuse cards.")
        available = [c for c in all_cards if not c.get('image')]
        
    return random.sample(available, min(len(available), count))

def clean_text(text):
    if not text: return ""
    text = re.sub(r'[*_`]', '', text) 
    text = re.sub(r'\s+', ' ', text).strip()
    return text

# --- RENDERING TOOLS ---

def get_font(size, variant="Regular"):
    # Try to load high quality fonts first
    fonts = {
        "Bold": ["Outfit-Bold.ttf", "Inter-Bold.ttf", "Roboto-Bold.ttf", "arialbd.ttf"],
        "Regular": ["Outfit-Regular.ttf", "Inter-Regular.ttf", "Roboto-Regular.ttf", "arial.ttf"],
        "Mono": ["JetBrainsMono-Bold.ttf", "Consolas.ttf", "courbd.ttf"]
    }
    
    # Check assets/fonts first, then Windows fonts
    candidates = fonts.get(variant, fonts["Regular"])
    search_paths = [
        os.path.join(SCRIPT_DIR, "assets", "fonts"),
        "C:\\Windows\\Fonts"
    ]
    
    for name in candidates:
        for p in search_paths:
            full_path = os.path.join(p, name)
            if os.path.exists(full_path):
                try: return ImageFont.truetype(full_path, size)
                except: continue
                
    # Fallback
    return ImageFont.load_default()

def wrap_text(text, font, max_width):
    lines = []
    if not text: return lines
    
    # Rough estimate to avoid super slow pixel checks
    avg_char_width = font.getbbox("x")[2]
    max_chars = int(max_width / (avg_char_width * 0.9)) # padding
    
    paragraphs = text.split('\n')
    for p in paragraphs:
        # Use textwrap for initial split
        wrapped = textwrap.wrap(p, width=max_chars) 
        
        # Verify visual width and adjust if needed
        for line in wrapped:
            # Check if line fits
            bbox = font.getbbox(line)
            w = bbox[2] - bbox[0]
            if w <= max_width:
                lines.append(line)
            else:
                # Forced split if textwrap estimation failed (rare)
                # Just take the line as is for now to avoid complexity, 
                # usually estimates are conservative enough.
                lines.append(line)
    return lines

def draw_rounded_rect(draw, bbox, radius, fill, outline=None, width=1):
    x0, y0, x1, y1 = bbox
    # Draw logic for rounded rect
    draw.rounded_rectangle(bbox, radius=radius, fill=fill, outline=outline, width=width)

def create_gradient_bg(width, height, c1, c2):
    base = Image.new('RGB', (width, height), c1)
    top = Image.new('RGB', (width, height), c1)
    bottom = Image.new('RGB', (width, height), c2)
    mask = Image.new('L', (width, height))
    mask_data = []
    for y in range(height):
        mask_data.extend([int(255 * (y / height))] * width)
    mask.putdata(mask_data)
    base.paste(bottom, (0, 0), mask)
    return base.convert("RGBA")

# --- COMPONENT RENDERERS ---

def draw_header(img, subject):
    draw = ImageDraw.Draw(img)
    
    # 1. Logo (Left)
    if os.path.exists(LOGO_PATH):
        logo = Image.open(LOGO_PATH).convert("RGBA")
        # Resize logo
        h_target = 80
        aspect = logo.width / logo.height
        w_target = int(h_target * aspect)
        logo = logo.resize((w_target, h_target), Image.Resampling.LANCZOS)
        img.paste(logo, (PADDING, PADDING - 10), logo)
    
    # Title Text next to Logo if needed (Optional)
    font_title = get_font(24, "Bold")
    draw.text((PADDING + 100, PADDING + 15), "PG PATHSCHEDULER", font=font_title, fill=(255, 255, 255, 200))

    # 2. Subject Badge (Right)
    font_badge = get_font(22, "Mono")
    # Estimate width
    badge_text = subject.upper()
    bbox = font_badge.getbbox(badge_text)
    txt_w = bbox[2] - bbox[0]
    txt_h = bbox[3] - bbox[1]
    
    pad_x, pad_y = 30, 15
    badge_w = txt_w + pad_x * 2
    badge_h = txt_h + pad_y * 2 + 10 # extra for alignment
    
    badge_x2 = W - PADDING
    badge_x1 = badge_x2 - badge_w
    badge_y1 = PADDING
    badge_y2 = badge_y1 + badge_h
    
    # Translucent Cyan BG
    overlay = Image.new('RGBA', img.size, (0,0,0,0))
    d_overlay = ImageDraw.Draw(overlay)
    
    d_overlay.rounded_rectangle(
        (badge_x1, badge_y1, badge_x2, badge_y2), 
        radius=25, 
        fill=(6, 182, 212, 30), 
        outline=(6, 182, 212, 120), 
        width=2
    )
    img.alpha_composite(overlay)
    
    # Text
    draw.text(
        (badge_x1 + pad_x, badge_y1 + pad_y), 
        badge_text, 
        font=font_badge, 
        fill=ACCENT_CYAN
    )

def draw_footer(img):
    draw = ImageDraw.Draw(img)
    font = get_font(22, "Regular")
    text = "MEDICAL EXCELLENCE"
    bbox = font.getbbox(text)
    w = bbox[2] - bbox[0]
    
    draw.text(
        ((W - w) / 2, H - 60), 
        text, 
        font=font, 
        fill=(255, 255, 255, 80),
        spacing=6
    )

def draw_glass_card_bg(img):
    # Main Glass Card Area
    card_margin_top = 220
    card_margin_bottom = 180
    card_margin_x = 60
    
    x1, y1 = card_margin_x, card_margin_top
    x2, y2 = W - card_margin_x, H - card_margin_bottom
    
    overlay = Image.new('RGBA', img.size, (0,0,0,0))
    d_ov = ImageDraw.Draw(overlay)
    
    # Fill: very subtle white
    d_ov.rounded_rectangle(
        (x1, y1, x2, y2), 
        radius=60, 
        fill=(255, 255, 255, 12), 
        outline=(255, 255, 255, 25), 
        width=2
    )
    
    # Add subtle shadow (simulated with multiple rectified rectangles if needed, 
    # but for simplicity in PIL, we rely on the contrast with background)
    
    img.alpha_composite(overlay)
    
    return (x1, y1, x2, y2) # Return content box

def render_card_front(card):
    # Base Layer
    img = create_gradient_bg(W, H, BG_TOP, BG_BOTTOM)
    
    draw_header(img, card.get('subject', 'General'))
    content_box = draw_glass_card_bg(img)
    draw_footer(img)
    
    draw = ImageDraw.Draw(img)
    
    # Center Text: Question
    cx1, cy1, cx2, cy2 = content_box
    card_w = cx2 - cx1
    card_h = cy2 - cy1
    
    question = clean_text(card.get('question', 'Question?'))
    
    # Dynamic Font Size
    font_size = 68
    if len(question) > 100: font_size = 58
    if len(question) > 200: font_size = 48
    
    font_q = get_font(font_size, "Bold")
    
    # Layout Text
    lines = wrap_text(question, font_q, card_w - 140) # padding inside card
    
    # Calculate total height
    line_height = font_q.getbbox("Ay")[3] + 15 # spacing
    total_h = len(lines) * line_height
    
    start_y = cy1 + (card_h - total_h) / 2
    
    # Draw Lines
    curr_y = start_y
    for line in lines:
        bbox = font_q.getbbox(line)
        lw = bbox[2] - bbox[0]
        draw.text(
            (cx1 + (card_w - lw) / 2, curr_y), 
            line, 
            font=font_q, 
            fill=(255, 255, 255, 255)
        )
        curr_y += line_height
        
    # Swipe Hint
    font_hint = get_font(24, "Bold")
    hint = "SWIPE TO REVEAL >>"
    bbox = font_hint.getbbox(hint)
    hw = bbox[2] - bbox[0]
    draw.text(
        ((W - hw) / 2, cy2 + 60), 
        hint, 
        font=font_hint, 
        fill=ACCENT_GOLD
    )
    
    return img

def render_card_back(card):
    # Base Layer
    img = create_gradient_bg(W, H, BG_TOP, BG_BOTTOM)
    
    draw_header(img, card.get('subject', 'General'))
    content_box = draw_glass_card_bg(img)
    draw_footer(img)
    
    cx1, cy1, cx2, cy2 = content_box
    card_w = cx2 - cx1
    
    # --- Answer Section (Top of Card) ---
    # Create a semi-solid green header area inside the glass card
    overlay = Image.new('RGBA', img.size, (0,0,0,0))
    d_ov = ImageDraw.Draw(overlay)
    
    ans_h = 240
    # Clip top radius is tricky, so draw a smaller rect or just simple rect
    # PIL doesn't support complex clipping paths easily.
    # We will draw a header box slightly inside with top radius.
    
    ax1, ay1 = cx1, cy1
    ax2, ay2 = cx2, cy1 + ans_h
    
    # We can effectively draw over the top part of the glass card
    d_ov.rounded_rectangle(
        (ax1, ay1, ax2, ay2), 
        radius=60,
        corners=(True, True, False, False), # Top corners only? PIL recent versions only
        fill=ACCENT_GREEN
    )
    
    # If `corners` param not supported (older PIL), draw full rect then clip bottom?
    # Safer fallback: Draw standard rounded rect
    try:
         d_ov.rounded_rectangle(
            (ax1, ay1, ax2, ay2), 
            radius=60,
            corners=(True, True, False, False),
            fill=(16, 185, 129, 230) # slight transparency
        )
    except:
         d_ov.rectangle((ax1, ay1, ax2, ay2), fill=(16, 185, 129, 230))
         
    img.alpha_composite(overlay)
    draw = ImageDraw.Draw(img)
    
    # Label
    font_lbl = get_font(20, "Bold")
    draw.text((ax1 + 60, ay1 + 50), "CORRECT ANSWER", font=font_lbl, fill=(0, 50, 20, 180))
    
    # Answer Text
    answer = clean_text(card.get('answer', 'Answer'))
    font_ans = get_font(54, "Bold")
    
    # Wrap Answer
    ans_lines = wrap_text(answer, font_ans, card_w - 120)
    # Clamp to max 2 lines
    if len(ans_lines) > 3: ans_lines = ans_lines[:3] 
    
    ay_text = ay1 + 90
    for line in ans_lines:
        draw.text((ax1 + 60, ay_text), line, font=font_ans, fill=(255, 255, 255, 255))
        ay_text += 60
        
    # --- Explanation Section ---
    expl_y_start = ay2 + 50
    
    font_expl_lbl = get_font(24, "Bold")
    draw.text((cx1 + 60, expl_y_start), "DEEP INSIGHT:", font=font_expl_lbl, fill=ACCENT_GOLD)
    
    exploration = clean_text(card.get('explanation', ''))
    
    # Dynamic sizing
    expl_max_h = cy2 - expl_y_start - 80
    expl_w = card_w - 120
    
    font_size = 38
    if len(exploration) > 200: font_size = 32
    if len(exploration) > 400: font_size = 28
    
    font_expl = get_font(font_size, "Regular")
    
    expl_lines = wrap_text(exploration, font_expl, expl_w)
    
    curr_y = expl_y_start + 50
    line_h = font_expl.getbbox("Ay")[3] + 12
    
    for line in expl_lines:
        if curr_y + line_h > cy2 - 40: break # simple clipping
        draw.text((cx1 + 60, curr_y), line, font=font_expl, fill=TEXT_MAIN)
        curr_y += line_h

    return img

def render_batch():
    print(f"--- FLASHCARD GENERATOR (PIL ENGINE) ---")
    cards = fetch_batch_questions(BATCH_SIZE)
    if not cards:
        print("No cards found!")
        return
        
    results = []
    
    for i, card in enumerate(cards):
        q_id = card.get('id', f"q_{int(time.time())}_{i}")
        print(f"Rendering Card {i+1}: {q_id}")
        
        # FRONT
        img_f = render_card_front(card)
        f_name = f"card_{i+1}_front.png"
        f_path = os.path.join(OUTPUT_DIR, f_name)
        img_f.save(f_path)
        
        # BACK
        img_b = render_card_back(card)
        b_name = f"card_{i+1}_back.png"
        b_path = os.path.join(OUTPUT_DIR, b_name)
        img_b.save(b_path)
        
        results.append({
            "id": q_id,
            "front_image": f_path,
            "back_image": b_path,
            "question": card.get('question'),
            "answer": card.get('answer'),
            "explanation": card.get('explanation'),
            "subject": card.get('subject')
        })
        
        save_history_entry(q_id)
        
    # JSON Output
    json_path = os.path.join(OUTPUT_DIR, "daily_flashcards.json")
    with open(json_path, "w", encoding='utf-8') as f:
        json.dump({
            "date": time.strftime("%Y-%m-%d"),
            "cards": results
        }, f, indent=4)

    print(f"Done. Saved {len(results)} cards to {OUTPUT_DIR}")

if __name__ == "__main__":
    render_batch()
