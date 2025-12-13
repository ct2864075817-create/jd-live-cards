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
import copy
import ast
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
        "Referer": "[https://item.jd.com/](https://item.jd.com/)",
        "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/webp,*/*;q=0.8",
        "Accept-Language": "zh-CN,zh;q=0.9",
        "Connection": "keep-alive"
    }

def scrape_jd_sku(sku):
    url = f"[https://item.jd.com/](https://item.jd.com/){sku}.html"
    info = {"sku": sku, "title": "", "image_url": ""}
    
    try:
        r = requests.get(url, headers=get_headers(), timeout=15)
        if "verify" in r.url or "passport" in r.url:
            return None

        r.encoding = r.apparent_encoding
        soup = BeautifulSoup(r.text, 'html.parser')
        
        raw_title = ""
        title_tag = soup.select_one("div.sku-name")
        if title_tag: raw_title = title_tag.get_text(strip=True)
        if not raw_title and soup.title: raw_title = soup.title.string.split('-')[0].strip()
        
        if raw_title:
            info["title"] = raw_title.replace("京东", "").replace("自营", "").strip()
        else:
            return None

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
        r = requests.get(url, headers=get_headers(), timeout=15)
        return BytesIO(r.content)
    except:
        return None

def extract_points_with_regex(text):
    """
    当JSON解析失败时，使用正则暴力提取卖点
    """
    points = {}
    for i in range(1, 5):
        key = f"selling_point_{i}"
        # 匹配模式：key 后面跟着冒号，然后是引号，然后是内容
        pattern = re.search(rf"['\"]?{key}['\"]?\s*:\s*['\"](.*?)['\"]", text, re.DOTALL)
        if pattern:
            points[key] = pattern.group(1)
    return points

def call_ai(product_name, api_key, base_url):
    if not api_key: return {}
    headers = {"Content-Type": "application/json", "Authorization": f"Bearer {api_key}"}
    
    prompt = f"""
    你是一位拥有10年经验的电商金牌选品总监，擅长挖掘“痛点营销”和“高转化话术”。
    请根据商品名称【{product_name}】，深度剖析用户痛点，撰写 4 个极具煽动性和转化力的直播手卡卖点。

    【核心要求】：
    1. **拒绝空话**：不要只说“好用”，要说出解决什么具体麻烦。
    2. **结构严格**：采用“痛点场景 + 解决方案 + 带来的利益”的结构。
    3. **详细具体**：每条卖点需包含一个【吸睛短标题】（6-10字）和一段【详细痛点阐述】（30-50字）。
    4. **数量**：必须生成 4 条。

    【输出格式】：
    请直接返回纯 JSON 格式数据，键名固定为：selling_point_1, selling_point_2, selling_point_3, selling_point_4。
    """
    
    data = {
        "model": "deepseek-chat", 
        "messages": [{"role": "user", "content": prompt}],
        "temperature": 0.7,
        "response_format": {"type": "json_object"}
    }
    try:
        resp = requests.post(f"{base_url}/chat/completions", headers=headers, json=data, timeout=40)
        content = resp.json()['choices'][0]['message']['content']
        
        # 清洗 Markdown
        content = content.replace("```json", "").replace("```", "").strip()
        
        # 多重解析保障
        try:
            return json.loads(content)
        except:
            try:
                return ast.literal_eval(content)
            except:
                return extract_points_with_regex(content)
    except:
        return {}

def duplicate_slide(pres):
    source = pres.slides[0]
    blank_slide_layout = pres.slide_layouts[6] 
    dest = pres.slides.add_slide(blank_slide_layout)

    for shp in source.shapes:
        el = shp.element
        newel = copy.deepcopy(el)
        dest.shapes._spTree.insert_element_before(newel, 'p:extLst')
    return dest

def fill_slide(slide, data):
    def replace(name, text):
        text_str = str(text)
        # 防套娃清洗
        if text_str.strip().startswith("{") and "selling_point" in text_str:
             text_str = "AI生成格式错误，请手动修改"

        for shape in slide.shapes:
            if shape.name == name and shape.has_text_frame:
                shape.text_frame.text = text_str
                return
            if shape.shape_type == 6: 
                for sub in shape.shapes:
                    if sub.name == name and sub.has_text_frame:
                        sub.text_frame.text = text_str
                        return

    replace("product_name", data['title'])
    replace("product_sku", data['sku']) 
    replace("price_live", data['price'])
    
    points = data.get('points', {})
    if not points:
        for i in range(1, 5):
            replace(f"selling_point_{i}", "智能卖点生成失败，请检查网络")
    else:
        for i in range(1, 5):
            content = points.get(f'selling_point_{i}', '')
            content = re.sub(r'^\d+\.?\s*', '', str(content))
            replace(f"selling_point_{i}", content)

    if data['image_data']:
        for shape in slide.shapes:
            if shape.name == "product_image":
                left, top, width, height = shape.left, shape.top, shape.width, shape.height
                sp = shape._element
                sp.getparent().remove(sp)
                slide.shapes.add_picture(data['image_data'], left, top, width, height)
                break

# --- 网页界面 ---
st.title("⚡ 京东直播手卡全自动生成器 (V4.2 终极稳定版)")
st.markdown("升级说明：增强了对 AI 回复格式的兼容性，杜绝乱码！")

# 侧边栏配置
with st.sidebar:
    st.header("⚙️ 配置")
    api_key = st.text_input("AI API Key", type="password", help="输入DeepSeek Key")
    base_url = st.text_input("Base URL", value="[https://api.deepseek.com](https://api.deepseek.com)")
    
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

if st.button("🚀 开始生成合集", type="primary"):
    if not skus_input:
        st.error("请输入 SKU")
        st.stop()
        
    if not os.path.exists("直播手卡模板.pptx"):
        st.error("找不到模板文件！请先在侧边栏上传模板。")
        st.stop()
    
    prs = Presentation("直播手卡模板.pptx")
    
    skus_text = skus_input.replace('，', ',').replace('\n', ',').replace(' ', ',')
    skus = [s.strip() for s in skus_text.split(',') if s.strip()]
    
    prices_text = prices_input.replace('，', ',').replace('\n', ',').replace(' ', ',')
    prices = [p.strip() for p in prices_text.split(',') if p.strip()]
    if not prices: prices = ["9.9"]
    
    progress_bar = st.progress(0)
    status_text = st.empty()
    
    success_count = 0
    
    for i, sku in enumerate(skus):
        if i > 0:
            sleep_time = random.uniform(3, 6)
            status_text.text(f"⏳ 防封暂停 {int(sleep_time)} 秒...")
            time.sleep(sleep_time)
            
        status_text.text(f"正在处理第 {i+1}/{len(skus)} 个商品: {sku} ...")
        
        current_price = prices[i] if i < len(prices) else prices[-1]
        
        info = scrape_jd_sku(sku)
        if not info:
            st.warning(f"SKU {sku} 抓取失败，已跳过。")
            continue
            
        info['price'] = current_price
        info['image_data'] = download_image(info['image_url'], sku)
        
        if api_key:
            info['points'] = call_ai(info['title'], api_key, base_url)
        else:
            info['points'] = {}
            
        if i == 0:
            current_slide = prs.slides[0]
        else:
            current_slide = duplicate_slide(prs)
            
        fill_slide(current_slide, info)
        success_count += 1
        
        progress_bar.progress((i + 1) / len(skus))
    
    status_text.text("正在保存文件...")
    
    output_ppt = BytesIO()
    prs.save(output_ppt)
    output_ppt.seek(0)
    
    if success_count > 0:
        st.success(f"🎉 成功生成 {success_count} 张手卡！")
        st.download_button(
            label="⬇️ 下载直播手卡合集 (PPTX)",
            data=output_ppt,
            file_name=f"直播手卡合集_{time.strftime('%m%d_%H%M')}.pptx",
            mime="application/vnd.openxmlformats-officedocument.presentationml.presentation"
        )
    else:
        st.error("没有生成任何有效手卡，请检查 SKU 或网络。")
