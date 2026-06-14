from __future__ import annotations
import dash
from dash import html, dcc, Input, Output, State
from dash.exceptions import PreventUpdate
import pandas as pd
import plotly.express as px
import requests
import base64
import io
import re
import dash_bootstrap_components as dbc

# GÜVENLİK VE APİ AYARLARI 
LM_STUDIO_URL = "http://127.0.0.1:1234/v1/chat/completions"
MODEL_NAME = "google/gemma-3n-e4b"


# TYPO-TOLERANT (YAZIM HATASI) YARDIMCI MOTORU

def levenshtein_distance(s1: str, s2: str) -> int:
    """İki kelime arasındaki harfsel değişim mesafesini hesaplar."""
    if len(s1) < len(s2):
        return levenshtein_distance(s2, s1)
    if len(s2) == 0:
        return len(s1)
    previous_row = list(range(len(s2) + 1))
    for i, c1 in enumerate(s1):
        current_row = [i + 1]
        for j, c2 in enumerate(s2):
            insertions = previous_row[j + 1] + 1
            deletions = current_row[j] + 1
            substitutions = previous_row[j] + (c1 != c2)
            current_row.append(min(insertions, deletions, substitutions))
        previous_row = current_row
    return previous_row[-1]

def is_close_match(word1: str, word2: str) -> bool:
    """Yazım hatalarını saptayarak kelimelerin birbirine benzerliğini doğrular."""
    w1 = word1.lower().strip()
    w2 = word2.lower().strip()
    if not w1 or not w2:
        return False
    # Çok kısa kelimelerde hata payı bırakmıyoruz
    if len(w1) <= 3 or len(w2) <= 3:
        return w1 == w2
    max_dist = 2 if max(len(w1), len(w2)) > 6 else 1
    if abs(len(w1) - len(w2)) > max_dist:
        return False
    return levenshtein_distance(w1, w2) <= max_dist


# YAPAY ZEKA GÜVENLİ ÇAĞRI METODU

def safe_ai_call(prompt: str) -> str:
    """Modelin bağlam dışına çıkmasını ve uydurma yapmasını engelleyen koruyucu katman."""
    MAX_CHARS = 12000
    if len(prompt) > MAX_CHARS:
        prompt = prompt[:MAX_CHARS] + "\n...[KISALTILDI]..."

    system_rules = (
        "Sen titiz ve uzman bir veri analistisin. "
        "SADECE verilen sonuç tablo, özet kart istatistikleri veya özet bilgilere göre konuş. "
        "Verilen verileri ve dosyaları kıyasla. "
        "Eksik bilgi varsa açıkça 'bu veri setinde yok' de. "
        "ASLA sayısal uydurma yapma. "
        "Cevapların Türkçe, kısa, net ve kurumsal bir dille yazılmış olsun."
    )

    try:
        payload = {
            "model": MODEL_NAME,
            "messages": [
                {"role": "user", "content": f"[KURALLAR]\n{system_rules}\n\n[VERİ/KARŞILAŞTIRMA SONUÇLARI]\n{prompt}"}
            ],
            "temperature": 0.2,
            "max_tokens": 500,
        }

        resp = requests.post(
            LM_STUDIO_URL,
            headers={"Content-Type": "application/json"},
            json=payload,
            timeout=60,
            allow_redirects=False 
        )
        resp.raise_for_status()
        return resp.json()["choices"][0]["message"]["content"].strip()
    except Exception as e:
        print("AI HATASI >>>", e)
        return "⚠️ AI şu anda kullanılamıyor. Lütfen LM Studio sunucunuzun açık ve modelin yüklenmiş olduğunu kontrol edin."

def is_smalltalk(q: str) -> bool:
    """Günlük selamlaşma ve sohbet başlangıçlarını filtreler."""
    q = (q or "").lower().strip()
    return any(w in q for w in ["nasılsın", "selam", "merhaba", "hey", "napıyorsun", "teşekkür", "sağ ol"])


# VERİ DOSYASI OKUMA (CSV / EXCEL)

def parse_contents(contents, filename):
    try:
        _, content_string = contents.split(",")
        decoded = base64.b64decode(content_string)

        if filename.lower().endswith(".csv"):
            text = None
            for enc in ["utf-8", "utf-8-sig", "cp1254", "latin1"]:
                try:
                    text = decoded.decode(enc)
                    break
                except Exception:
                    pass
            if text is None:
                return None

            try:
                df = pd.read_csv(io.StringIO(text), sep=";")
                if df.shape[1] == 1:
                    df = pd.read_csv(io.StringIO(text), sep=",")
            except Exception:
                df = pd.read_csv(io.StringIO(text), sep=None, engine="python")

        elif filename.lower().endswith((".xls", ".xlsx")):
            ext = filename.lower().split(".")[-1]
            if ext == "xlsx":
                df = pd.read_excel(io.BytesIO(decoded), engine="openpyxl")
            else:
                df = pd.read_excel(io.BytesIO(decoded), engine="xlrd")
        else:
            return None

        # Sütun isimlerini küçük harfe ve alt tire formatına çevir (Kurumsal standardizasyon)
        df.columns = (
            df.columns.astype(str)
            .str.strip()
            .str.lower()
            .str.replace(" ", "_")
        )

        for c in df.columns:
            if df[c].dtype == "object":
                coerced = pd.to_numeric(df[c], errors="coerce")
                if coerced.notna().mean() > 0.6:
                    df[c] = coerced

        return df.to_dict(orient="records")
    except Exception as e:
        print("Dosya okuma hatası:", e)
        return None

# İNTENT VE ANALİZ MOTORU (OPERASYON KARARLARI)

def detect_intent(question: str) -> dict:
    q = (question or "").lower().strip()
    intent = {
        "mode": "analyze",
        "op": None,
        "graph": None,
        "top_n": None,
        "show_all": False,
        "others_bucket": True,
    }

    if any(w in q for w in ["özet", "kıyasla", "karşılaştır", "karsilastir", "fark", "analiz et", "yorumla", "özetle", "ozetle"]):
        intent["mode"] = "summary"
    if any(w in q for w in ["hepsi", "tümü", "tamamı", "hepsini göster", "tümünü göster"]):
        intent["show_all"] = True
    if any(w in q for w in ["diğer olmasın", "others olmasın"]):
        intent["others_bucket"] = False

    # Grafik Türü Kararı
    if "pasta" in q or "pie" in q:
        intent["graph"] = "pie"
    elif any(w in q for w in ["çizgi", "trend", "zaman", "aylık", "yıllık", "tarih", "akış"]):
        intent["graph"] = "line"
    else:
        intent["graph"] = "bar"

    # Limit Yakalama (Top N)
    m = re.search(r"(top|ilk|en çok)\s*(\d+)", q)
    if not m:
        m = re.search(r"(\d+)\s*(ürün|urun|kategori|musteri|müşteri|sporcu|kayıt)", q)
    if m:
        nums = re.findall(r"\d+", m.group(0))
        if nums:
            intent["top_n"] = int(nums[0])

    # Matematiksel Operasyon Tespiti
    if any(w in q for w in ["kaç", "kac", "sayısı", "sayi", "count", "tane"]):
        intent["op"] = "count"
    if any(w in q for w in ["ortalama", "average", "mean"]):
        intent["op"] = "mean"
    if any(w in q for w in ["toplam", "sum", "ciro", "satış", "satis", "sales", "değer", "satılan", "satilan", "adet"]):
        if intent["op"] is None:
            intent["op"] = "sum"
    if any(w in q for w in ["trend", "zaman", "aylık", "tarih"]):
        intent["op"] = "trend"
        intent["graph"] = "line"

    if intent["op"] is None:
        intent["op"] = "sum"

    return intent

def score_column_by_question(col: str, question: str) -> int:
    """
    Sözlük tabanlı ve typo-tolerant gelişmiş puanlama motoru.
    Gelişmiş mesafe saptaması sayesinde 'pieve' gibi yazım hatalarını dahi adet (piece) sütunu ile eşleştirir.
    """
    q = (question or "").lower()
    c = (col or "").lower()
    score = 0
    
    # Doğrudan tam eşleşme kontrolü
    if c in q:
        score += 10

    mapping = {
        "gender": ["gender", "cinsiyet", "kadın", "erkek"],
        "sales": ["sales", "satış", "satis", "ciro", "revenue", "tutar"],
        "profit": ["profit", "kâr", "kar"],
        "price": ["price", "fiyat", "ücret", "ucret", "tutar", "fiyatı"],
        # Piece/Adet/Miktar anlamsal olarak typo korumasıyla eşlendi
        "piece": ["piece", "pieces", "adet", "tane", "miktar", "satılan", "satilan", "sayı", "sayisi", "stok", "stok_adedi", "quantity", "qty", "count", "satis_adedi", "satış_adedi", "sipariş_adedi", "siparis_adedi"],
        "score": ["score", "puan", "not", "grade"],
        "date": ["date", "tarih", "zaman", "ay", "yıl", "trend"],
        "product": ["product", "ürün", "urun", "kategori", "category"],
    }

    tokens = re.findall(r"[a-zA-Zçğıöşü0-9_]+", q)

    # 1. Kelime Haritası (Mapping) Eşleştirmesi (Typo-Tolerant)
    for key, words in mapping.items():
        has_match = False
        for w in words:
            if w in q:
                has_match = True
                break
            # Token bazlı yakınlık testi
            for t in tokens:
                if is_close_match(t, w):
                    has_match = True
                    break
            if has_match:
                break
                
        if has_match:
            if key in c:
                score += 8
            if any(is_close_match(c, w) or w in c for w in words):
                score += 5

    # 2. Doğrudan Token Karşılaştırması (Karakter Düzeyinde Yakınlık)
    for t in tokens:
        if t:
            if t in c:
                score += 3
            elif is_close_match(t, c):
                score += 6  # Yakın typo durumunda yüksek öncelik puanı
                
    return score

def infer_columns(df: pd.DataFrame, question: str, intent: dict) -> tuple[str|None, str|None, str|None]:
    cats = [c for c in df.columns if df[c].dtype == "object" or str(df[c].dtype).startswith("category")]
    nums = df.select_dtypes(include="number").columns.tolist()
    
    date_cols = []
    for c in df.columns:
        if df[c].dtype.kind in "Mm":
            date_cols.append(c)
        elif df[c].dtype == "object":
            sample = df[c].dropna().astype(str).head(10)
            if not sample.empty and pd.to_datetime(sample, errors="coerce").notna().mean() >= 0.6:
                date_cols.append(c)

    date_col = max(date_cols, key=lambda c: score_column_by_question(c, question)) if intent["op"] == "trend" and date_cols else None
    group_col = max(cats, key=lambda c: score_column_by_question(c, question)) if cats else None
    metric_col = max(nums, key=lambda c: score_column_by_question(c, question)) if intent["op"] in ["sum", "mean"] and nums else None

    if intent["op"] == "count":
        metric_col = None

    return group_col, metric_col, date_col


# TEKLİ DOSYA HESAPLAMA MOTORU 

def compute_result(df: pd.DataFrame, question: str, intent: dict, group: str|None, metric: str|None, date_col: str|None):
    """Sadece tek bir dosyayı hedef alan sorularda hatasız hesaplama yapar."""
    op = intent["op"]
    q = (question or "").lower()

    if intent["mode"] == "summary":
        basic = {
            "rows": int(len(df)),
            "cols": df.columns.tolist(),
            "numeric_cols": df.select_dtypes(include="number").columns.tolist(),
            "categorical_cols": [c for c in df.columns if df[c].dtype == "object"],
        }
        return None, None, basic, "summary"

    filter_value = None
    wants_both_gender = ("kadın" in q or "kadin" in q) and ("erkek" in q)

    if op == "count" and group and group in df.columns and not wants_both_gender:
        uniq = df[group].dropna().astype(str).str.strip().unique().tolist()
        for u in uniq:
            if u.lower() in q:
                filter_value = u
                break

    # TREND ANALİZİ
    if op == "trend":
        if not date_col or date_col not in df.columns:
            return None, None, "⚠️ Zaman serisi analizi için uygun tarih sütunu tespit edilemedi.", "text"
        dft = df.copy()
        dft[date_col] = pd.to_datetime(dft[date_col], errors="coerce", infer_datetime_format=True)
        dft = dft.dropna(subset=[date_col])
        if dft.empty:
            return None, None, "⚠️ Tarih sütununda geçerli veri bulunamadı.", "text"

        span_days = (dft[date_col].max() - dft[date_col].min()).days if len(dft) else 0
        freq = "M" if span_days > 60 else "D"

        if metric is None or metric not in dft.columns:
            res = dft.set_index(date_col).resample(freq).size().reset_index(name="count")
            fig = px.line(res, x=date_col, y="count", title=f"Zamana Göre Kayıt Frekansı ({freq})")
            return res, fig, {"date_col": date_col, "metric": "count", "freq": freq}, "table"
        else:
            res = dft.set_index(date_col).resample(freq)[metric].sum().reset_index()
            fig = px.line(res, x=date_col, y=metric, title=f"Zamana Göre {metric} Akışı ({freq})")
            return res, fig, {"date_col": date_col, "metric": metric, "freq": freq}, "table"

    # ADET SAYIMI (COUNT)
    if op == "count":
        if group and group in df.columns:
            s = df[group]
            if filter_value is not None:
                cnt = int((s.astype(str).str.strip().str.lower() == str(filter_value).lower()).sum())
                text = f"✅ **{group}** içerisinde **'{filter_value}'** değerine sahip kayıt sayısı: **{cnt}**"
                grouped = pd.DataFrame({group: [str(filter_value), "Diğer"], "count": [cnt, len(df) - cnt]})
                fig = px.pie(grouped, names=group, values="count", title=f"{group} Dağılımı (Seçilen Filtre: {filter_value})")
                return grouped, fig, text, "text"

            res = df.groupby(group).size().reset_index(name="count").sort_values("count", ascending=False)
            if intent["graph"] == "pie":
                top_n = intent["top_n"] or 10
                if not intent["show_all"] and intent["others_bucket"]:
                    top = res.head(top_n).copy()
                    rest = res.iloc[top_n:]
                    if not rest.empty:
                        top = pd.concat([top, pd.DataFrame([{group: "Diğer", "count": int(rest["count"].sum())}])], ignore_index=True)
                    res2 = top
                else:
                    res2 = res.head(intent["top_n"]) if (intent["top_n"] and not intent["show_all"]) else res
                fig = px.pie(res2, names=group, values="count", title=f"{group} Dağılım Oranları")
            else:
                res2 = res.head(intent["top_n"]) if (intent["top_n"] and not intent["show_all"]) else res
                fig = px.bar(res2, x=group, y="count", title=f"{group} Dağılım Miktarları")
            return res, fig, {"group": group, "metric": "count"}, "table"

        return None, None, f"✅ Toplam satır sayısı: **{len(df)}**", "text"

    # TOPLAM VEYA ORTALAMA HESAPLAMA (SUM / MEAN)
    if op in ["sum", "mean"]:
        if not metric or metric not in df.columns:
            intent2 = dict(intent)
            intent2["op"] = "count"
            return compute_result(df, question, intent2, group, None, date_col)

        if group and group in df.columns:
            if op == "mean":
                res = df.groupby(group)[metric].mean().reset_index().sort_values(metric, ascending=False)
                title = f"{group} Kırılımında Ortalama {metric}"
            else:
                res = df.groupby(group)[metric].sum().reset_index().sort_values(metric, ascending=False)
                title = f"{group} Kırılımında Toplam {metric}"

            res2 = res.head(intent["top_n"]) if (intent["top_n"] and not intent["show_all"]) else res

            if intent["graph"] == "pie":
                top_n = intent["top_n"] or 10
                if not intent["show_all"] and intent["others_bucket"]:
                    top = res.head(top_n).copy()
                    rest = res.iloc[top_n:]
                    if not rest.empty:
                        top = pd.concat([top, pd.DataFrame([{group: "Diğer", metric: float(rest[metric].sum())}])], ignore_index=True)
                    res2 = top
                fig = px.pie(res2, names=group, values=metric, title=title)
            elif intent["graph"] == "line":
                fig = px.line(res2, x=group, y=metric, title=title)
            else:
                fig = px.bar(res2, x=group, y=metric, title=title)

            return res, fig, {"group": group, "metric": metric, "op": op}, "table"

        val = float(df[metric].mean()) if op == "mean" else float(df[metric].sum())
        label = "ortalama" if op == "mean" else "toplam"
        return None, None, f"✅ **{metric}** sütununa ait {label} değer: **{val:.2f}**", "text"

    return None, None, "⚠️ Soru anlaşılamadı veya matematiksel karşılık bulunamadı.", "text"

# ÇİFT DOSYA KARŞILAŞTIRMA VE HESAP MOTORU

def compute_comparative_result(df1: pd.DataFrame, df2: pd.DataFrame, question: str, intent: dict, group: str|None, metric: str|None, date_col: str|None):
    op = intent["op"]
    q = (question or "").lower()

    # Karşılaştırma özeti istendiğinde, ortak metrik seçimi geliştirildi
    if intent["mode"] == "summary" or any(w in q for w in ["kıyasla", "karşılaştır", "fark"]):
        len1, len2 = len(df1), len(df2)
        nums1 = df1.select_dtypes(include="number").columns.tolist()
        nums2 = df2.select_dtypes(include="number").columns.tolist()
        common_nums = list(set(nums1).intersection(set(nums2)))
        
        summary_metric = metric
        if not summary_metric:
            if common_nums:
                summary_metric = common_nums[0]
            elif nums1:
                summary_metric = nums1[0]
        
        comparison_data = {
            "dosya_1_satir": len1,
            "dosya_2_satir": len2,
            "satir_fark_yuzde": ((len2 - len1) / len1) * 100 if len1 else 0
        }
        
        fig = None
        # Ortak sayısal sütun üzerinden kıyaslama yap
        if summary_metric and summary_metric in df1.columns and summary_metric in df2.columns:
            sum1 = float(df1[summary_metric].sum())
            sum2 = float(df2[summary_metric].sum())
            mean1 = float(df1[summary_metric].mean())
            mean2 = float(df2[summary_metric].mean())
            
            comparison_data["metric"] = summary_metric
            comparison_data["dosya_1_toplam"] = sum1
            comparison_data["dosya_2_toplam"] = sum2
            comparison_data["toplam_degisim_yuzde"] = ((sum2 - sum1) / sum1) * 100 if sum1 else 0
            comparison_data["dosya_1_ortalama"] = mean1
            comparison_data["dosya_2_ortalama"] = mean2
            
            fig_df = pd.DataFrame({
                "Veri Kaynağı": ["1. Dosya (Referans)", "2. Dosya (Karşılaştırma)"],
                f"Toplam {summary_metric}": [sum1, sum2],
                f"Ortalama {summary_metric}": [mean1, mean2]
            })
            fig = px.bar(fig_df, x="Veri Kaynağı", y=f"Toplam {summary_metric}", color="Veri Kaynağı", title=f"Genel {summary_metric} Karşılaştırması")
        else:
            # Sadece satır sayısı (boyut) karşılaştırması yap
            fig_df = pd.DataFrame({
                "Veri Kaynağı": ["1. Dosya (Referans)", "2. Dosya (Karşılaştırma)"],
                "Satır Sayısı": [len1, len2]
            })
            fig = px.bar(fig_df, x="Veri Kaynağı", y="Satır Sayısı", color="Veri Kaynağı", title="Dosya Veri Boyutları Karşılaştırması (Satır Sayıları)")
            
        return None, fig, comparison_data, "comparison_summary"

    # Detaylı gruplu karşılaştırma
    common_cols = list(set(df1.columns).intersection(set(df2.columns)))
    if group not in common_cols or (metric and metric not in common_cols):
        cats1 = [c for c in df1.columns if df1[c].dtype == "object"]
        cats2 = [c for c in df2.columns if df2[c].dtype == "object"]
        common_cats = list(set(cats1).intersection(set(cats2)))
        if common_cats:
            group = common_cats[0]
        else:
            return None, None, "⚠️ Karşılaştırma yapmak için iki dosyada ortak kategorik sütun bulunamadı.", "text"

    # KATEGORİK KARŞILAŞTIRMA 
    if group and group in common_cols:
        if op == "count":
            g1 = df1.groupby(group).size().reset_index(name="1. Dosya")
            g2 = df2.groupby(group).size().reset_index(name="2. Dosya")
            title_suffix = "Kayıt Adetleri"
        elif op == "mean" and metric:
            g1 = df1.groupby(group)[metric].mean().reset_index(name="1. Dosya")
            g2 = df2.groupby(group)[metric].mean().reset_index(name="2. Dosya")
            title_suffix = f"Ortalama {metric}"
        else:
            metric = metric if metric else df1.select_dtypes(include="number").columns[0]
            g1 = df1.groupby(group)[metric].sum().reset_index(name="1. Dosya")
            g2 = df2.groupby(group)[metric].sum().reset_index(name="2. Dosya")
            title_suffix = f"Toplam {metric}"

        merged = pd.merge(g1, g2, on=group, how="outer").fillna(0)
        melted = merged.melt(id_vars=[group], value_vars=["1. Dosya", "2. Dosya"], var_name="Veri Seti", value_name="Değer")
        top_categories = merged.sort_values(by=["1. Dosya", "2. Dosya"], ascending=False).head(intent["top_n"] or 10)[group].tolist()
        melted_filtered = melted[melted[group].isin(top_categories)]

        fig = px.bar(
            melted_filtered, 
            x=group, 
            y="Değer", 
            color="Veri Seti", 
            barmode="group",
            title=f"Dosyalar Arası Karşılaştırma: {group} Bazında {title_suffix}"
        )
        
        return merged, fig, {"group": group, "metric": metric or "Kayıt Adedi", "op": op}, "table"

    return None, None, "⚠️ Karşılaştırma yapılamadı. Girdilerinizi kontrol edin.", "text"

def make_ai_context(df: pd.DataFrame, question: str, result_df: pd.DataFrame | None, meta: dict | str):
    base = {
        "question": question,
        "rows": int(len(df)),
        "columns": df.columns.tolist(),
        "meta": meta,
    }
    sample = df.head(8).to_dict(orient="records")
    out = f"Genel Bilgi: {base}\nÖrnek 8 satır: {sample}\n"
    if isinstance(result_df, pd.DataFrame) and not result_df.empty:
        out += f"Sonuç Tablosu (İlk 15): {result_df.head(15).to_dict(orient='records')}\n"
    out += "Bu sonucu 3-4 cümleyle profesyonelce analiz et. Sayısal hesaplamaları baştan yapma, verilen değerleri yorumla."
    return out

# CALLBACK KAYIT MOTORU 

def register_callbacks(app):
    
    # 1. TEMA DEĞİŞTİRME MEKANİZMASI
    @app.callback(
        [Output("current-theme-store", "data"),
         Output("theme-toggle-btn", "children"),
         Output("theme-toggle-btn", "color")],
        Input("theme-toggle-btn", "n_clicks"),
        State("current-theme-store", "data"),
        prevent_initial_call=True
    )
    def toggle_theme_state(n_clicks, current_theme):
        if current_theme == "dark":
            return "light", "🌙 Karanlık Tema", "dark"
        else:
            return "dark", "☀️ Aydınlık Tema", "secondary"

    # Dinamik olarak DOM başlığına CSS enjekte eden clientside callback 
    app.clientside_callback(
        """
        function(theme) {
            let themeLink = document.getElementById("theme-link");
            if (!themeLink) {
                themeLink = document.createElement("link");
                themeLink.id = "theme-link";
                themeLink.rel = "stylesheet";
                document.head.appendChild(themeLink);
            }
            if (theme === "light") {
                themeLink.href = "https://cdn.jsdelivr.net/npm/bootswatch@5.3.2/dist/flatly/bootstrap.min.css";
            } else {
                themeLink.href = "https://cdn.jsdelivr.net/npm/bootswatch@5.3.2/dist/darkly/bootstrap.min.css";
            }
            return "";
        }
        """,
        Output("theme-style-injector", "children"),
        Input("current-theme-store", "data")
    )

    # 2. 1. DOSYA YÜKLEME CALLBACK'İ
    @app.callback(
        [Output("uploaded-data-store-1", "data"), Output("upload-status-1", "children")],
        Input("upload-data-1", "contents"), State("upload-data-1", "filename"), prevent_initial_call=True
    )
    def upload_data_1(contents, filename):
        if contents is None: return dash.no_update, dash.no_update
        data = parse_contents(contents, filename)
        if data is not None:
            return data, html.P(f"✅ {filename[:20]}...", style={"color": "lightgreen", "margin": "0"})
        return dash.no_update, html.P("❌ Hatalı format", style={"color": "red", "margin": "0"})

    # 3. 2. DOSYA YÜKLEME CALLBACK'İ
    @app.callback(
        [Output("uploaded-data-store-2", "data"), Output("upload-status-2", "children")],
        Input("upload-data-2", "contents"), State("upload-data-2", "filename"), prevent_initial_call=True
    )
    def upload_data_2(contents, filename):
        if contents is None: return dash.no_update, dash.no_update
        data = parse_contents(contents, filename)
        if data is not None:
            return data, html.P(f"✅ {filename[:20]}...", style={"color": "lightgreen", "margin": "0"})
        return dash.no_update, html.P("❌ Hatalı format", style={"color": "red", "margin": "0"})

    # 4. CHAT VE ANALİZ CALLBACK'İ (DURUM: Çift Tetiklemeli ve Hibrit Modlu!)
    @app.callback(
        [Output("chat-output", "children"),
         Output("user-input", "value"),
         Output("dashboard-content", "children")],
        [Input("submit-button", "n_clicks"),
         Input("user-input", "n_submit")],
        [State("uploaded-data-store-1", "data"),
         State("uploaded-data-store-2", "data"),
         State("user-input", "value"),
         State("chat-output", "children")],
        prevent_initial_call=True
    )
    def chat(n_clicks, n_submit, data1, data2, question, chat_history):
        if not n_clicks and not n_submit:
            raise PreventUpdate

        chat_history = chat_history or []
        if not question:
            return chat_history, "", dash.no_update

        # Sohbet / Merhabalaşma yakalama
        if is_smalltalk(question):
            chat_history += [
                html.P(question, style={"textAlign": "right", "fontWeight": "bold"}),
                html.P("Selam, harika görünüyorsun kanka! Analiz etmek istediğin veri setlerini sol panelden yükledikten sonra dilediğini sorabilirsin. 😄", style={"textAlign": "left"})
            ]
            return chat_history, "", dash.no_update

        # En azından bir dosya yüklenmiş olmalı
        if not data1 and not data2:
            return chat_history, "", html.H4("⚠️ Analize başlamak için lütfen en az bir adet veri kümesi yükleyin.")

        #  AKILLI VE NOKTA ATIŞI SORGULAMA SÜZGEÇİ
       
        q_low = (question or "").lower().strip()
        
        # 1. Dosya Odaklı Kelimeler
        file1_focused = any(kw in q_low for kw in [
            "birinci", "dosya 1", "dosya1", "1. dosya", "1.dosya", "ilk dosya", "ilk veri", "referans", "kafe", "cafe", "market"
        ]) and not any(kw in q_low for kw in ["market2", "ikinci", "2."])
        
        # 2. Dosya Odaklı Kelimeler
        file2_focused = any(kw in q_low for kw in [
            "ikinci", "dosya 2", "dosya2", "2. dosya", "2.dosya", "karşılaştırma dosyası", "karsilastirma dosyasi", "sonraki dosya", "yeni veri", "sporcu", "market2"
        ]) and not any(kw in q_low for kw in ["birinci", "1."])

        # Eğer soruda kıyaslama/karşılaştırma kelimeleri geçiyorsa, iki dosya yüklüyken zorunlu olarak karşılaştırma modunda kalalım
        is_compare_query = any(kw in q_low for kw in ["karşılaştır", "karsilastir", "kıyasla", "kiyasla", "fark", "farkı", "farklari", "farkları", "yoy", "değişim", "degisim", "kıyas", "kiyas", "ikisi", "dosyaları", "dosyalari", "veri setlerini", "tabloları", "tablolari"])

        is_single_mode = False
        active_data = None
        mode_label = ""

        # Tek dosya yüklüyse zaten otomatik tekli mod çalışır
        if data1 and not data2:
            is_single_mode = True
            active_data = data1
            mode_label = "1. Dosya (Referans) Modu"
        elif data2 and not data1:
            is_single_mode = True
            active_data = data2
            mode_label = "2. Dosya (Karşılaştırma) Modu"
        # Her iki dosya da yüklüyse ve kullanıcı özellikle tek bir dosyayı hedeflediyse
        elif data1 and data2:
            if not is_compare_query:
                if file1_focused and not file2_focused:
                    is_single_mode = True
                    active_data = data1
                    mode_label = "1. Dosya (Referans) Modu"
                elif file2_focused and not file1_focused:
                    is_single_mode = True
                    active_data = data2
                    mode_label = "2. Dosya (Karşılaştırma) Modu"

        # TEKLİ DOSYA ANALİZİ (Tamamen Bağımsız ve Ortak Sütun Şartı Yoktur)
        if is_single_mode:
            df = pd.DataFrame(active_data)
            df.columns = df.columns.astype(str).str.strip().str.lower().str.replace(" ", "_")

            intent = detect_intent(question)
            group, metric, date_col = infer_columns(df, question, intent)

            # Bağımsız hesaplama metodunu çağırıyoruz
            res_table, fig, info, out_type = compute_result(df, question, intent, group, metric, date_col)
            
            # Eğer istek sadece bir dosyanın özetiyse, şık bir Dashboard Özet Kartı hazırlayıp döndürelim!
            if out_type == "summary":
                ctx = make_ai_context(df, question, None, info)
                ai_text = safe_ai_call(ctx)
                
                chat_history += [
                    html.P(question, style={"textAlign": "right", "fontWeight": "bold"}),
                    html.P(f"💡 [{mode_label}] {ai_text}", style={"textAlign": "left"}),
                ]
                
                # Akademik düzeyde görsel özet paneli
                summary_card = html.Div([
                    html.Div([
                        html.H4(f"📊 {mode_label} - Veri Kümesi Özeti", className="text-primary mb-3", style={"fontWeight": "700"}),
                        html.Hr(className="border-secondary mb-3"),
                        dbc.Row([
                            dbc.Col([
                                html.Div([
                                    html.P("Satır Sayısı", className="text-muted mb-1", style={"fontSize": "12px"}),
                                    html.H3(f"{info['rows']:,}", className="text-success m-0", style={"fontWeight": "bold"})
                                ], className="p-3 bg-light bg-opacity-10 rounded border border-secondary mb-3")
                            ], width=6),
                            dbc.Col([
                                html.Div([
                                    html.P("Sütun Sayısı", className="text-muted mb-1", style={"fontSize": "12px"}),
                                    html.H3(f"{len(info['cols'])}", className="text-info m-0", style={"fontWeight": "bold"})
                                ], className="p-3 bg-light bg-opacity-10 rounded border border-secondary mb-3")
                            ], width=6),
                        ]),
                        html.Div([
                            html.Strong("Sütun Listesi: ", className="text-muted"),
                            html.Span(", ".join(info['cols']), className="text-light")
                        ], className="mb-2"),
                        html.Div([
                            html.Strong("Sayısal Sütunlar: ", className="text-muted"),
                            html.Span(", ".join(info['numeric_cols']) if info['numeric_cols'] else "Yok", className="text-success")
                        ], className="mb-2"),
                        html.Div([
                            html.Strong("Kategorik Sütunlar: ", className="text-muted"),
                            html.Span(", ".join(info['categorical_cols']) if info['categorical_cols'] else "Yok", className="text-info")
                        ], className="mb-2"),
                    ], className="p-4")
                ], className="shadow rounded border border-secondary bg-dark bg-opacity-50")
                
                return chat_history, "", summary_card

            graph = dcc.Graph(figure=fig) if fig is not None else dash.no_update
            ctx = make_ai_context(df, question, res_table, info)
            ai_text = safe_ai_call(ctx)

            chat_history += [
                html.P(question, style={"textAlign": "right", "fontWeight": "bold"}),
                html.P(f"💡 [{mode_label}] {ai_text}", style={"textAlign": "left"}),
            ]
            return chat_history, "", graph

        # ÇİFT DOSYALI GERÇEK KARŞILAŞTIRMA MODU (YoY ANALİZİ)

        df1 = pd.DataFrame(data1)
        df2 = pd.DataFrame(data2)
        df1.columns = df1.columns.astype(str).str.strip().str.lower().str.replace(" ", "_")
        df2.columns = df2.columns.astype(str).str.strip().str.lower().str.replace(" ", "_")

        intent = detect_intent(question)
        group, metric, date_col = infer_columns(df1, question, intent)

        result_table, fig, info, out_type = compute_comparative_result(df1, df2, question, intent, group, metric, date_col)

        if out_type == "text":
            chat_history += [
                html.P(question, style={"textAlign": "right", "fontWeight": "bold"}),
                html.P(str(info), style={"textAlign": "left"}),
            ]
            return chat_history, "", dash.no_update

        graph = dcc.Graph(figure=fig) if fig is not None else dash.no_update

        # YAPAY ZEKA BAĞLAM HAZIRLAMA VE KARŞILAŞTIRMALI YORUM
        if out_type == "comparison_summary":
            ai_prompt = (
                f"Kullanıcı Sorusu: {question}\n"
                f"Dosya 1 Satır Sayısı: {info['dosya_1_satir']}\n"
                f"Dosya 2 Satır Sayısı: {info['dosya_2_satir']}\n"
                f"Satır Sayısı Değişim Yüzdesi: %{info['satir_fark_yuzde']:.2f}\n"
            )
            if "metric" in info:
                ai_prompt += (
                    f"Karşılaştırılan Ortak Sayısal Metrik: {info['metric']}\n"
                    f"Dosya 1 Toplam: {info['dosya_1_toplam']:.2f}\n"
                    f"Dosya 2 Toplam: {info['dosya_2_toplam']:.2f}\n"
                    f"Değişim Oranı: %{info['toplam_degisim_yuzde']:.2f}\n"
                    f"Dosya 1 Ortalama: {info['dosya_1_ortalama']:.2f}\n"
                    f"Dosya 2 Ortalama: {info['dosya_2_ortalama']:.2f}\n"
                )
            ai_prompt += "Bu iki farklı veri kümesinin genel boyutlarını ve performans değişimini profesyonelce yorumla."
        else:
            # Tablo üzerinden karşılaştırmalı yorum
            sample_merged = result_table.head(10).to_dict(orient="records") if result_table is not None else "Veri yok"
            ai_prompt = (
                f"Kullanıcı Sorusu: {question}\n"
                f"Gruplanan Sütun: {info['group']}\n"
                f"Analiz Edilen Metrik: {info['metric']}\n"
                f"İki Dosyadan Gruplanan Karşılaştırma Matrisi (İlk 10): {sample_merged}\n"
                f"1. Dosya sütunu referans veri setini, 2. Dosya sütunu ise karşılaştırılan yeni veri setini temsil etmektedir.\n"
                f"Hangi kategorilerde büyüme, hangilerinde daralma olduğunu detaylandırarak 3-4 cümleyle Türkçe analiz et."
            )

        ai_text = safe_ai_call(ai_prompt)

        chat_history += [
            html.P(question, style={"textAlign": "right", "fontWeight": "bold"}),
            html.P(ai_text, style={"textAlign": "left"}),
        ]

        return chat_history, "", graph
