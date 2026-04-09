import streamlit as st
import psycopg2
import hashlib
import pandas as pd
import requests
from io import BytesIO
from PIL import Image
import numpy as np
import zipfile
from bs4 import BeautifulSoup
import time

# ✨ Selenium 관련 라이브러리 추가
from selenium import webdriver
from selenium.webdriver.chrome.service import Service
from selenium.webdriver.chrome.options import Options
from selenium.webdriver.common.by import By
from webdriver_manager.chrome import ChromeDriverManager
from selenium.webdriver.common.keys import Keys

# ---------------------------------------------------------
# 1. DB 설정 및 보안
# ---------------------------------------------------------
DB_HOST = "database-1.cozmuw2eq103.us-east-1.rds.amazonaws.com"
DB_NAME = "girin"
DB_USER = "postgres"
DB_PASS = "Ppooii**9098" 
DB_PORT = "5432"

def get_db_connection():
    return psycopg2.connect(host=DB_HOST, database=DB_NAME, user=DB_USER, password=DB_PASS, port=DB_PORT, sslmode='require')

def hash_password(password):
    return hashlib.sha256(password.encode()).hexdigest()

# ---------------------------------------------------------
# 2. ✨ 자동 로그인 및 크롤링 로직 (승우 담당)
# ---------------------------------------------------------

# 셀레니움을 이용해 자동으로 로그인하고 쿠키를 가져오는 함수
def get_cookie_automatically(base_url, user_id, user_pw):
    login_url = f"{base_url}/member/login.html"
    
    options = Options()
    options.add_argument("--headless") # 화면 없이 실행
    options.add_argument("--no-sandbox")
    options.add_argument("--disable-dev-shm-usage")
    
    try:
        driver = webdriver.Chrome(service=Service(ChromeDriverManager().install()), options=options)
        driver.get(login_url)
        time.sleep(2) # 페이지 로딩 대기

 # 카페24 일반적인 로그인 폼 선택자
        driver.find_element(By.ID, "member_id").send_keys(user_id)
        
        # 비밀번호를 입력하고, 이어서 바로 엔터(RETURN) 키를 전송합니다!
        pw_input = driver.find_element(By.ID, "member_passwd")
        pw_input.send_keys(user_pw)
        pw_input.send_keys(Keys.RETURN) 
        
        time.sleep(3) # 로그인 처리 대기

        # 현재 브라우저의 쿠키를 requests 형식으로 변환
        cookies = driver.get_cookies()
        cookie_dict = {c['name']: c['value'] for c in cookies}
        cookie_str = "; ".join([f"{k}={v}" for k, v in cookie_dict.items()])
        
        driver.quit()
        return cookie_str
    except Exception as e:
        if 'driver' in locals(): driver.quit()
        st.error(f"자동 로그인 시도 중 오류 발생: {e}")
        return None

def split_image_by_whitespace(image_url):
    try:
        response = requests.get(image_url, timeout=10)
        img = Image.open(BytesIO(response.content)).convert('RGB')
        arr = np.array(img)
        row_means = np.mean(arr, axis=(1, 2))
        content_rows = np.where(row_means < 250)[0]
        if len(content_rows) == 0: return [img]
        images, start = [], content_rows[0]
        for i in range(1, len(content_rows)):
            if content_rows[i] - content_rows[i-1] > 15: 
                end = content_rows[i-1]
                if end - start > 50: images.append(img.crop((0, start, img.width, end)))
                start = content_rows[i]
        end = content_rows[-1]
        if end - start > 50: images.append(img.crop((0, start, img.width, end)))
        return images if images else [img]
    except: return None

def get_shop_product_images(shop_url, user_cookie):
    product_images = []
    try:
        headers = {
            'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36',
            'Cookie': user_cookie
        }
        res = requests.get(shop_url, headers=headers)
        soup = BeautifulSoup(res.text, 'html.parser')
        
        links = []
        for a in soup.select('a[href*="/product/detail.html"]'):
            href = a['href']
            if href.startswith('/'): href = '/'.join(shop_url.split('/')[:3]) + href
            if href not in links: links.append(href)
        
        links = links[:30]
        progress_bar = st.progress(0)
        
        for i, link in enumerate(links):
            try:
                p_res = requests.get(link, headers=headers)
                p_soup = BeautifulSoup(p_res.text, 'html.parser')
                detail_images = p_soup.select('#prdDetail img, .cont img, .detail_area img')
                for img in detail_images:
                    src = img.get('src') or img.get('ec-data-src')
                    if src:
                        if src.startswith('//'): src = 'https:' + src
                        elif src.startswith('/'): src = '/'.join(shop_url.split('/')[:3]) + src
                        if not any(item['url'] == src for item in product_images):
                            product_images.append({"url": src, "name": f"Product_{i+1}"})
                time.sleep(0.3)
            except: continue
            progress_bar.progress((i + 1) / len(links))
        return product_images
    except Exception as e:
        st.error(f"크롤링 오류: {e}"); return []

def create_zip_file(image_data_list):
    zip_buffer = BytesIO()
    with zipfile.ZipFile(zip_buffer, "w", zipfile.ZIP_DEFLATED) as zip_file:
        for folder_name, file_name, img in image_data_list:
            img_buffer = BytesIO()
            img.save(img_buffer, format="JPEG")
            zip_file.writestr(f"{folder_name}/{file_name}", img_buffer.getvalue())
    return zip_buffer.getvalue()

# ---------------------------------------------------------
# 3. 화면 구성 (민규 담당)
# ---------------------------------------------------------
st.set_page_config(page_title="이미지 다운로더 프로 V3", layout="wide")
st.title("🖼️ 개별이미지 다운로더 프로 (v3.0 - 자동화)")

if 'logged_in' not in st.session_state: st.session_state['logged_in'] = False
if 'shop_cookie' not in st.session_state: st.session_state['shop_cookie'] = ""
if 'processed_data' not in st.session_state: st.session_state['processed_data'] = None

if st.session_state['logged_in']:
    st.sidebar.success(f"👤 {st.session_state['username']}님")
    if st.sidebar.button("로그아웃"):
        st.session_state['logged_in'] = False; st.session_state['shop_cookie'] = ""; st.rerun()

    # --- 일반 사용자 화면 ---
    mode = st.radio("🛠️ 작업 모드:", ["🔗 직접 URL 입력", "🏪 쇼핑몰 일괄 자동 추출"], horizontal=True)
    st.markdown("---")

    if mode == "🔗 직접 URL 입력":
        urls_input = st.text_area("🔗 이미지 주소(URL)들을 입력하세요:", height=150)
        if st.button("분할 시작", type="primary", use_container_width=True):
            urls = [u.strip() for u in urls_input.split('\n') if u.strip()]
            if urls:
                with st.spinner('작업 중...'):
                    all_processed = []
                    conn = get_db_connection(); cur = conn.cursor()
                    for idx, t_url in enumerate(urls):
                        imgs = split_image_by_whitespace(t_url)
                        if imgs:
                            all_processed.append({"folder": f"Link_{idx+1}", "url": t_url, "images": imgs})
                            cur.execute("INSERT INTO download_logs (username, image_url) VALUES (%s, %s)",(st.session_state['username'], t_url))
                    conn.commit(); conn.close()
                    st.session_state['processed_data'] = all_processed
                    st.success("✅ 완료!")

    else:
        # ✨ 쇼핑몰 로그인 세션 구역
        with st.expander("🔑 쇼핑몰 간편 로그인 설정 (최초 1회)", expanded=not st.session_state['shop_cookie']):
            col_id, col_pw = st.columns(2)
            s_id = col_id.text_input("쇼핑몰 아이디")
            s_pw = col_pw.text_input("쇼핑몰 비밀번호", type="password")
            if st.button("쇼핑몰 로그인 인증하기"):
                with st.spinner('유령 브라우저가 쇼핑몰에 로그인 중입니다...'):
                    # 기린 쇼핑몰 기본 주소 사용 (주소에 맞춰 자동 로그인)
                    cookie = get_cookie_automatically("https://gi-rin.com", s_id, s_pw)
                    if cookie:
                        st.session_state['shop_cookie'] = cookie
                        st.success("✅ 쇼핑몰 인증 성공! 이제 아래 주소를 입력하세요.")
                    else:
                        st.error("❌ 로그인 실패. 아이디/비번을 확인하거나 캡챠 보안을 확인하세요.")

        shop_url = st.text_input("🏪 카테고리 주소 입력:", placeholder="https://gi-rin.com/product/list.html?cate_no=43")
        
        if st.button("일괄 수집 및 분할 시작", type="primary", use_container_width=True):
            if not st.session_state['shop_cookie']:
                st.warning("먼저 위 '간편 로그인 설정'에서 쇼핑몰 인증을 완료해 주세요.")
            elif not shop_url:
                st.warning("카테고리 주소를 입력해 주세요.")
            else:
                with st.spinner('상세페이지를 순회하며 이미지를 자르고 있습니다...'):
                    found = get_shop_product_images(shop_url, st.session_state['shop_cookie'])
                    if found:
                        all_processed = []
                        conn = get_db_connection(); cur = conn.cursor()
                        for item in found:
                            imgs = split_image_by_whitespace(item['url'])
                            if imgs:
                                all_processed.append({"folder": item['name'], "url": item['url'], "images": imgs})
                                cur.execute("INSERT INTO download_logs (username, image_url) VALUES (%s, %s)",(st.session_state['username'], item['url']))
                        conn.commit(); conn.close()
                        st.session_state['processed_data'] = all_processed
                        st.success("✅ 모든 작업 완료!")
                    else:
                        st.error("이미지를 찾지 못했습니다. 인증 세션이 만료되었을 수 있습니다.")

    # 결과 출력 (이전과 동일)
    if st.session_state['processed_data']:
        # ... (이전의 이미지 그리드 및 ZIP 다운로드 코드) ...
        # [코드 간결화를 위해 결과 출력부는 v2.1과 동일하게 유지]
        st.markdown("---")
        data = st.session_state['processed_data']
        all_zip, sel_zip = [], []
        for item in data:
            with st.expander(f"📁 {item['folder']}"):
                cols = st.columns(4)
                for idx, img in enumerate(item['images']):
                    fname = f"split_{idx+1}.jpg"; all_zip.append((item['folder'], fname, img))
                    with cols[idx%4]:
                        st.image(img, use_container_width=True)
                        if st.checkbox("선택", key=f"s_{item['folder']}_{idx}"): sel_zip.append((item['folder'], fname, img))
        st.download_button("📦 전체 다운로드", create_zip_file(all_zip), "all.zip", "application/zip", use_container_width=True)

else:
    # 로그인 화면
    st.info("로그인 후 이용 가능합니다.")
    tab_l, tab_s = st.tabs(["로그인", "가입요청"])
    with tab_l:
        l_id = st.text_input("ID")
        l_pw = st.text_input("PW", type="password")
        if st.button("로그인"):
            conn = get_db_connection(); cur = conn.cursor()
            cur.execute("SELECT password, status FROM users WHERE username = %s", (l_id,))
            res = cur.fetchone()
            if res and res[0] == hash_password(l_pw) and (l_id=='admin' or res[1]=='approved'):
                st.session_state['logged_in'] = True; st.session_state['username'] = l_id; st.rerun()
            else: st.error("인증 실패 또는 승인 대기")
            conn.close()
    with tab_s:
        # ... (가입 요청 UI) ...
        st.write("가입 요청 정보 입력...")