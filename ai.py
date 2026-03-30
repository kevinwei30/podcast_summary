from pathlib import Path

from config import ANTHROPIC_API_KEY

SUMMARY_PROMPT = """\
你是一位專業的財經摘要助手。以下是今天《游庭皓的財經皓角》podcast 的逐字稿。
本集標題：{episode_title}

請用繁體中文撰寫一份清晰、有條理的摘要，包含：

1. 📌 今日重點（3-5 個 bullet points）
2. 📊 市場動態（指數、個股、商品等具體數字）
3. 💡 主持人核心觀點
4. ⚠️  需要特別關注的風險或機會

格式要易於閱讀，讓沒有時間收聽的人也能快速掌握精華。

逐字稿如下：
---
{transcript}
---
"""

INFOGRAPHIC_PROMPT = """\
你是一位專業的網頁設計師。請根據以下財經podcast摘要，生成一個適合 Instagram 發布的單頁資訊圖表 HTML。

設計規格：
- 尺寸：1080×1350px（Instagram 直式比例）
- 風格：深色金融主題（深藍/深灰背景，金色/白色文字）
- 字型：使用 Google Fonts Noto Sans TC（支援繁體中文）
- 版面：由上至下分為以下區塊

版面結構：
1. 頂部 Header：「財經皓角」標題 + 集數標題（較小字）+ 日期
2. 📌 今日重點：3-5 個重點 bullet points
3. 📊 市場動態：指數、個股等數據（漲用綠色，跌用紅色）
4. 💡 核心觀點：主持人觀點 1-2 句
5. ⚠️ 風險關注：1-2 個需注意事項
6. 底部 Footer：「游庭皓的財經皓角」小字

技術要求：
- 完整的 HTML 文件，包含所有 CSS（inline 或 <style> 標籤）
- 使用 @import 載入 Google Fonts
- 固定寬度 1080px，高度 1350px，overflow: hidden
- CSS 請保持簡潔，避免過多裝飾性元素，以確保內容完整輸出
- 只回傳 HTML 程式碼，不要加任何說明文字

摘要內容：
---
{summary}
---

集數標題：{episode_title}
日期：{date_str}
"""


def summarize(transcript: str, episode_title: str) -> tuple[str, float]:
    import anthropic
    client = anthropic.Anthropic(api_key=ANTHROPIC_API_KEY)
    print("🤖 Summarizing with Claude…")
    message = client.messages.create(
        model="claude-sonnet-4-6",
        max_tokens=4096,
        messages=[{
            "role": "user",
            "content": SUMMARY_PROMPT.format(
                episode_title=episode_title,
                transcript=transcript[:50000],
            ),
        }],
    )
    input_tokens  = message.usage.input_tokens
    output_tokens = message.usage.output_tokens
    cost_usd = (input_tokens / 1_000_000 * 3) + (output_tokens / 1_000_000 * 15)
    print(f"   Input tokens  : {input_tokens}")
    print(f"   Output tokens : {output_tokens}")
    print(f"   Claude cost   : ${cost_usd:.4f} USD")
    return message.content[0].text, cost_usd


def generate_infographic(summary: str, episode_title: str, date_str: str, out_dir: Path) -> tuple[Path, float]:
    import anthropic
    from playwright.sync_api import sync_playwright

    client = anthropic.Anthropic(api_key=ANTHROPIC_API_KEY)
    print("🎨 Generating infographic HTML with Claude…")
    message = client.messages.create(
        model="claude-sonnet-4-6",
        max_tokens=8096,
        messages=[{
            "role": "user",
            "content": INFOGRAPHIC_PROMPT.format(
                summary=summary,
                episode_title=episode_title,
                date_str=date_str,
            ),
        }],
    )
    input_tokens  = message.usage.input_tokens
    output_tokens = message.usage.output_tokens
    cost_usd = (input_tokens / 1_000_000 * 3) + (output_tokens / 1_000_000 * 15)
    print(f"   Input tokens  : {input_tokens}")
    print(f"   Output tokens : {output_tokens}")
    print(f"   Claude cost   : ${cost_usd:.4f} USD")

    html = message.content[0].text.strip()
    if html.startswith("```"):
        html = html.split("\n", 1)[-1].rsplit("```", 1)[0].strip()

    html_path = out_dir / "infographic.html"
    html_path.write_text(html, encoding="utf-8")

    print("📸 Rendering infographic with Playwright…")
    png_path = out_dir / "infographic.png"
    with sync_playwright() as p:
        browser = p.chromium.launch()
        page = browser.new_page(viewport={"width": 1080, "height": 1350})
        page.set_content(html, wait_until="networkidle")
        page.screenshot(path=str(png_path), clip={"x": 0, "y": 0, "width": 1080, "height": 1350})
        browser.close()

    size_kb = png_path.stat().st_size / 1024
    print(f"   Saved → {png_path} ({size_kb:.0f} KB)")
    return png_path, cost_usd
