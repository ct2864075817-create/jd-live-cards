import streamlit as st
import pandas as pd
from pptx import Presentation
import os
import time
import requests
from bs4 import BeautifulSoup
import json
import re
import random
import shutil
import zipfile
from io import BytesIO

# --- 页面配置 ---
st.set_page_config(page_title="京东直播手卡生成器 Web版", page_icon="⚡", layout="wide")

# --- 核心逻辑 ---
USER_AGENTS = [
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36",
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
]

def get_headers():
    return {
        "User-Agent": random.choice(USER_AGENTS),
        "Referer": "https://item.jd.com/",
        "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/webp,*/*;q=0.8",
        "Accept-Language": "zh-CN,zh;q=0.9"
    }

def scrape_jd_sku(sku):
    url = f"https://item.jd.com/{sku}.html"
    info = {"sku": sku, "title": "", "image_url": ""}
    
    try:
        r = requests.get(url, headers=get_headers(), timeout=10)
        r.encoding = r.apparent_encoding
        soup = BeautifulSoup(r.text, 'html.parser')
        
        # 抓标题
        raw_title = ""
        title_tag = soup.select_one("div.sku-name")
        if title_tag: raw_title = title_tag.get_text(strip=True)
        if not raw_title and soup.title: raw_title = soup.title.string.split('-')[0].strip()
        
        if raw_title:
            info["title"] = raw_title.replace("京东", "").replace("自营", "").strip()
        else:
            info["title"] = f"商品_{sku}"

        # 抓主图
        candidates = []
        img_tag = soup.select_one("#spec-img")
        if img_tag:
            candidates.append(img_tag.get('data-origin'))
            candidates.append(img_tag.get('src'))
        patterns = re.findall(r'//img\d{1,2}\.360buyimg\.com/n[01]/jfs/[^"]+\.jpg', r.text)
        candidates.extend(patterns)

        valid_imgs = []
        for img in candidates:
            if img and "jfs" in img and ".jpg" in img:
                if not img.startswith("http"):
                    img = "https:" + img if img.startswith("//") else "https://" + img
                img = img.replace("/n1/", "/n0/").replace("/n5/", "/n0/")
                valid_imgs.append(img)

        if valid_imgs:
            info["image_url"] = valid_imgs[0]
        
        return info
    except Exception as e:
        return None

def download_image(url, sku):
    if not url: return None
    try:
        r = requests.get(url, headers=get_headers(), timeout=10)
        filename = f"temp_img_{sku}.jpg"
        with open(filename, 'wb') as f: f.write(r.content)
        return filename
    except:
        return None

def call_ai(product_name, api_key, base_url):
    if not api_key: return {}
    headers = {"Content-Type": "application/json", "Authorization": f"Bearer {api_key}"}
    
    # --- V3.0 核心升级：高转化痛点提示词 ---
    prompt = f"""
    你是一位拥有10年经验的电商金牌选品总监，擅长挖掘“痛点营销”和“高转化话术”。
    请根据商品名称【{product_name}】，深度剖析用户痛点，撰写 4 个极具煽动性和转化力的直播手卡卖点。

    【核心要求】：
    1. **拒绝空话**：不要只说“好用”、“便宜”，要说出具体好在哪里，解决什么具体麻烦。
    2. **结构严格**：采用“痛点场景 + 解决方案 + 带来的利益”的结构。
    3. **详细具体**：每条卖点需包含一个【吸睛短标题】（6-10字）和一段【详细痛点阐述】（30-50字）。
    4. **数量**：必须生成 4 条。

    【参考范例（以保温杯为例）】：
    - 卖点1：**拒绝喝冷水，24小时锁温**：上班忙起来总忘喝水，想喝时水早凉了伤胃？它采用双层抽真空技术，早上倒的热水，晚上还是烫嘴的，随时温暖你的胃。
    - 卖点2：**不漏水才是硬道理**：包里文件电脑最怕水杯漏水！这款采用食品级硅胶密封圈，倒置狂甩都不漏，放心随便塞进包里，出行更安心。

    【输出格式】：
    请直接返回纯 JSON 格式数据，键名固定为：selling_point_1, selling_point_2, selling_point_3, selling_point_4。
    """
    
    data = {
        "model": "deepseek-chat", 
        "messages": [{"role": "user", "content": prompt}],
        "temperature": 0.8, # 稍微提高创造性
        "response_format": {"type": "json_object"}
    }
    try:
        resp = requests.post(f"{base_url}/chat/completions", headers=headers, json=data, timeout=40) # 增加超时时间，因为生成内容变多了
        return json.loads(resp.json()['choices'][0]['message']['content'])
    except:
        return {}

def generate_ppt(data, template_path, output_dir):
    if not os.path.exists(template_path): return None
    sku = data['sku']
    prs = Presentation(template_path)
    slide = prs.slides[0]

    def replace(name, text):
        for shape in slide.shapes:
            if shape.name == name and shape.has_text_frame:
                shape.text_frame.text = str(text)
                return
            if shape.shape_type == 6: 
                for sub in shape.shapes:
                    if sub.name == name and sub.has_text_frame:
                        sub.text_frame.text = str(text)
                        return

    replace("product_name", data['title'])
    replace("product_sku", data['sku']) 
    replace("price_live", data['price'])
    
    points = data.get('points', {})
    for i in range(1, 5):
        # 这里会将 "标题：详细内容" 组合在一起填入文本框
        # 也可以根据需求只填内容，但现在的提示词生成的是一段完整的话
        content = points.get(f'selling_point_{i}', '')
        
        # 自动清洗一下可能的格式问题 (比如去掉了开头多余的 "1.")
        content = re.sub(r'^\d+\.?\s*', '', str(content))
        
        replace(f"selling_point_{i}", content)

    if data['image_local']:
        found_img = False
        for shape in slide.shapes:
            if shape.name == "product_image":
                left, top, width, height = shape.left, shape.top, shape.width, shape.height
                sp = shape._element
                sp.getparent().remove(sp)
                slide.shapes.add_picture(data['image_local'], left, top, width, height)
                found_img = True
                break
    
    save_path = os.path.join(output_dir, f"{sku}.pptx")
    prs.save(save_path)
    return save_path

# --- 网页界面 ---
st.title("⚡ 京东直播手卡全自动生成器 (V3.0 高转化版)")
st.markdown("升级说明：优化了AI算法，现在能生成更加详细、直击痛点的直播话术！")

# 侧边栏配置
with st.sidebar:
    st.header("⚙️ 配置")
    api_key = st.text_input("AI API Key", type="password", help="输入DeepSeek Key")
    base_url = st.text_input("Base URL", value="https://api.deepseek.com")
    
    st.markdown("---")
    st.info("💡 请确保【直播手卡模板.pptx】已上传到服务器目录")
    
    uploaded_template = st.file_uploader("或上传你的PPT模板", type="pptx")
    if uploaded_template:
        with open("直播手卡模板.pptx", "wb") as f:
            f.write(uploaded_template.getbuffer())
        st.success("模板已更新！")

# 主界面
col1, col2 = st.columns([1, 1])
with col1:
    skus_input = st.text_area("1. 输入 SKU (批量，逗号或换行分隔)", height=200, placeholder="1000123456\n1000888888")
with col2:
    prices_input = st.text_area("2. 输入直播专享价 (对应左侧SKU顺序)", height=200, placeholder="9.9\n12.8\n(如果只填一个，则全部通用)")
    st.caption("注：第一行价格对应第一行SKU，以此类推。如果价格输少了，剩下的商品会自动复用最后一个价格。")

if st.button("🚀 开始生成", type="primary"):
    if not skus_input:
        st.error("请输入 SKU")
        st.stop()
    
    output_dir = "web_output"
    if os.path.exists(output_dir): shutil.rmtree(output_dir)
    os.makedirs(output_dir)
    
    # 清洗输入
    skus_text = skus_input.replace('，', ',').replace('\n', ',').replace(' ', ',')
    skus = [s.strip() for s in skus_text.split(',') if s.strip()]
    
    prices_text = prices_input.replace('，', ',').replace('\n', ',').replace(' ', ',')
    prices = [p.strip() for p in prices_text.split(',') if p.strip()]
    if not prices: prices = ["9.9"]
    
    progress_bar = st.progress(0)
    status_text = st.empty()
    
    generated_files = []
    
    for i, sku in enumerate(skus):
        status_text.text(f"正在处理: {sku} ({i+1}/{len(skus)})...")
        
        if i < len(prices):
            current_price = prices[i]
        else:
            current_price = prices[-1] 
        
        info = scrape_jd_sku(sku)
        
        if not info:
            st.warning(f"SKU {sku} 抓取失败，请检查SKU是否正确或网络连接。")
            continue
            
        info['price'] = current_price
        info['image_local'] = download_image(info['image_url'], sku)
        
        if api_key:
            info['points'] = call_ai(info['title'], api_key, base_url)
        else:
            info['points'] = {}
        
        ppt_path = generate_ppt(info, "直播手卡模板.pptx", output_dir)
        if ppt_path:
            generated_files.append(ppt_path)
        
        if info['image_local'] and os.path.exists(info['image_local']):
            os.remove(info['image_local'])
            
        progress_bar.progress((i + 1) / len(skus))
    
    status_text.text("处理完成！正在打包...")
    
    if generated_files:
        zip_buffer = BytesIO()
        with zipfile.ZipFile(zip_buffer, "w") as zf:
            for file_path in generated_files:
                zf.write(file_path, os.path.basename(file_path))
        
        st.success(f"成功生成 {len(generated_files)} 个文件！")
        st.download_button(
            label="⬇️ 下载所有手卡 (ZIP)",
            data=zip_buffer.getvalue(),
            file_name="直播手卡合集.zip",
            mime="application/zip"
        )
    else:
        st.error("没有生成任何文件，请检查 SKU 是否正确，或联系管理员查看后台日志。")