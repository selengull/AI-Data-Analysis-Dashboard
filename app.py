from __future__ import annotations
import dash
import dash_bootstrap_components as dbc
from dash import html, dcc

# ==========================================
# UYGULAMA BAŞLATMA & TEMA AYARI
# ==========================================
# İlk açılış için ciddi ve profesyonel bir koyu tema (DARKLY) seçiyoruz.
# Tema geçişini dinamik yönetebilmek için stil sayfalarını clientside_callback ile güncelleyeceğiz.
app = dash.Dash(
    __name__, 
    external_stylesheets=[dbc.themes.DARKLY],
    meta_tags=[{"name": "viewport", "content": "width=device-width, initial-scale=1"}]
)
app.title = "AI Destekli Çift Dosya Karşılaştırma Sistemi"

# ==========================================
# KURUMSAL ARAYÜZ (LAYOUT) TASARIMI
# ==========================================
app.layout = dbc.Container([
    # Hafıza depoları (Bellek içi dinamik veri saklama alanları)
    dcc.Store(id="uploaded-data-store-1"),  # 1. Dosya Belleği
    dcc.Store(id="uploaded-data-store-2"),  # 2. Dosya Belleği
    dcc.Store(id="current-theme-store", data="dark"),  # Mevcut tema durumu (dark/light)
    
    # CSS'i dinamik enjekte edeceğimiz görünmez yardımcı div
    html.Div(id="theme-style-injector"),

    # ÜST BAR: Başlık ve Tema Değiştirme Butonu
    dbc.Row([
        dbc.Col(
            html.H2("📊 AI Destekli Karşılaştırmalı Veri Analiz Paneli", className="my-3 text-start", style={"fontWeight": "700"}),
            width=9
        ),
        dbc.Col(
            dbc.Button(
                "☀️ Aydınlık Tema", 
                id="theme-toggle-btn", 
                color="secondary", 
                className="my-3 w-100",
                style={"fontWeight": "600"}
            ),
            width=3,
            className="d-flex align-items-center"
        )
    ], className="border-bottom border-secondary mb-4 pb-2"),

    # ANA PANEL: Sol (Çift Dosya Yükleme & Chat) ve Sağ (Raporlama ve Grafik)
    dbc.Row([
        
        # 1. SOL PANEL (Genişlik: 4)
        dbc.Col([
            # Kart 1: 1. Dosya (Referans)
            dbc.Card([
                dbc.CardHeader("1. Veri Kümesi ", style={"fontWeight": "600"}),
                dbc.CardBody([
                    dcc.Upload(
                        id="upload-data-1",
                        children=html.Div([
                            "Sürükle veya ", html.A("Göz At", style={"color": "#0d6efd", "fontWeight": "bold"})
                        ]),
                        style={
                            "width": "100%", "height": "50px", "lineHeight": "50px",
                            "borderWidth": "2px", "borderStyle": "dashed", "borderRadius": "8px",
                            "textAlign": "center", "cursor": "pointer"
                        },
                        multiple=False
                    ),
                    html.Div(id="upload-status-1", className="mt-2 text-center text-muted", style={"fontSize": "13px"})
                ])
            ], className="mb-2 shadow-sm"),

            # Kart 2: 2. Dosya (Karşılaştırma)
            dbc.Card([
                dbc.CardHeader("2. Veri Kümesi ", style={"fontWeight": "600"}),
                dbc.CardBody([
                    dcc.Upload(
                        id="upload-data-2",
                        children=html.Div([
                            "Sürükle veya ", html.A("Göz At", style={"color": "#198754", "fontWeight": "bold"})
                        ]),
                        style={
                            "width": "100%", "height": "50px", "lineHeight": "50px",
                            "borderWidth": "2px", "borderStyle": "dashed", "borderRadius": "8px",
                            "textAlign": "center", "cursor": "pointer"
                        },
                        multiple=False
                    ),
                    html.Div(id="upload-status-2", className="mt-2 text-center text-muted", style={"fontSize": "13px"})
                ])
            ], className="mb-3 shadow-sm"),
            
            # Kart 3: Soru-Cevap (Chat) Alanı
            dbc.Card([
                dbc.CardHeader("💬 Doğal Dil Tabanlı Soru-Cevap", style={"fontWeight": "600"}),
                dbc.CardBody([
                    html.Div(
                        id="chat-output",
                        style={
                            "height": "250px", "overflowY": "auto", "padding": "10px",
                            "borderRadius": "8px", "border": "1px solid #444", 
                            "marginBottom": "15px"
                        },
                        className="bg-opacity-10 bg-light"
                    ),
                    # dcc.Input kullanarak Enter tuşunu n_submit ile yakalıyoruz
                    dcc.Input(
                        id="user-input", 
                        placeholder="Örn: Dosyaların kâr oranlarını kıyasla...", 
                        type="text",
                        className="form-control mb-2", 
                        autoComplete="off"
                    ),
                    dbc.Button("Analizi Başlat", id="submit-button", color="primary", className="w-100", style={"fontWeight": "600"})
                ])
            ], className="shadow-sm")
        ], width=12, lg=4),
        
        # 2. SAĞ PANEL: Grafik ve Yorum Gösterim Alanı (Genişlik: 8)
        dbc.Col([
            dbc.Card([
                dbc.CardHeader("📈 Raporlama ve Dönemsel Performans Görselleştirme Alanı", style={"fontWeight": "600"}),
                dbc.CardBody([
                    html.Div(
                        id="dashboard-content",
                        children=[
                            html.Div([
                                html.I(className="bi bi-arrow-left-right fs-1 text-muted"),
                                html.H4("Sistem Karşılaştırma Analizine Hazır", className="text-muted mt-3"),
                                html.P("Tek bir dosya yükleyerek standart analize başlayabilir ya da iki farklı dosya yükleyerek dönemsel karşılaştırmalı A/B analizi yapabilirsiniz.", className="text-muted")
                            ], className="text-center py-5 my-5")
                        ]
                    )
                ])
            ], className="shadow-sm", style={"minHeight": "605px"})
        ], width=12, lg=8)
        
    ], className="g-4")
], fluid=True, style={"paddingLeft": "30px", "paddingRight": "30px"})


# ÇALIŞTIRMA BLOĞU

if __name__ == "__main__":
    print("🚀 Sunucu başlatılıyor...")
    # Döngüsel içe aktarma hatasını önlemek için callbacks modülünü tam bu noktada çağırıyoruz
    import callbacks
    
    # callbacks.py dosyasındaki kayıt fonksiyonunu çalıştırıp tetikleyicileri bağlıyoruz
    callbacks.register_callbacks(app)
    
    # Portu kilitlenmeleri önlemek için 8070 yaptık
    print("🌍 Lütfen tarayıcınızda şu adresi açın: http://127.0.0.1:8070")
    app.run(debug=True, port=8070, dev_tools_hot_reload=False)