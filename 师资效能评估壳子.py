import streamlit as st
import streamlit.components.v1 as components
import pandas as pd
import requests
import json
import re

# ==============================================================================
# 1. 核心配置与 API 初始化
# ==============================================================================
st.set_page_config(layout="wide", page_title="HKA 师资效能评估 AI版")

# 强制从 Secrets 读取 Key
try:
    API_KEY = st.secrets["SILICONFLOW_API_KEY"]
except Exception:
    st.error("❌ 严重错误：未检测到 SILICONFLOW_API_KEY。请在 .streamlit/secrets.toml 中配置 Key。")
    st.stop()

# ==============================================================================
# 2. 后端功能函数 (修复版：增强容错解析)
# ==============================================================================

@st.cache_data(show_spinner=False)
def ai_parse_excel(df):
    """
    修复版：使用正则提取 JSON 对象，容忍 AI 返回格式错误或连体 JSON
    """
    # 1. 数据预处理：如果数据量太大，限制前 50 行以保证稳定性（可选，根据需求调整）
    # df = df.head(50) 
    
    try:
        csv_content = df.to_csv(index=False)
    except Exception as e:
        return None, f"数据转换CSV失败: {str(e)}"
    
    # 2. System Prompt 强化格式要求
    target_schema = """
    {
        "name": "姓名",
        "age": 30,
        "subject": "学科",
        "edu": 1, 
        "titleLevel": 1,
        "rawTitle": "原始职称"
    }
    """
    
    system_prompt = f"""
    你是一个数据清洗程序。请读取 CSV 数据并转换为 JSON 对象流。
    
    【转换规则】
    1. **必须**为每一行数据生成一个独立的 JSON 对象。
    2. 字段映射：
       - titleLevel: 正高=5, 高级=4, 一级=3, 二级=2, 其他=1
       - edu: 包含"硕/博/研究生"=2, 否则=1
    3. **不要**返回 Markdown 格式，**不要**解释。
    4. 如果某行数据有问题，请跳过该行，不要中断。
    
    【单条数据模版】:
    {target_schema}
    """

    user_prompt = f"请处理以下数据:\n{csv_content}"

    try:
        url = "https://api.siliconflow.cn/v1/chat/completions"
        headers = {
            "Authorization": f"Bearer {API_KEY}",
            "Content-Type": "application/json"
        }
        payload = {
            "model": "deepseek-ai/DeepSeek-V3.2", # 使用 V3.2 甚至 V3
            "messages": [
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_prompt}
            ],
            "stream": False,
            "temperature": 0.1,
            "max_tokens": 8192
        }
        
        response = requests.post(url, json=payload, headers=headers)
        
        if response.status_code != 200:
            return None, f"API请求失败: {response.text}"

        response_data = response.json()
        if "choices" not in response_data:
            return None, f"API返回异常: {response_data}"
            
        content = response_data["choices"][0]["message"]["content"]
        
        # ==========================================================
        # 核心修复：使用正则表达式提取所有 JSON 对象
        # ==========================================================
        final_list = []
        
        # 1. 尝试直接标准解析（如果 AI 很听话返回了数组）
        try:
            # 移除可能存在的 markdown 标记
            clean_content = content.replace("```json", "").replace("```", "").strip()
            parsed = json.loads(clean_content)
            if isinstance(parsed, list):
                return parsed, None
            if isinstance(parsed, dict):
                 # 处理 {"data": [...]} 的情况
                for v in parsed.values():
                    if isinstance(v, list): return v, None
        except:
            pass # 标准解析失败，进入容错模式
            
        # 2. 容错解析：正则提取每一个 {...} 块
        # 这个正则是非贪婪匹配最外层的 {}，假设 json 内部没有嵌套的大括号结构，
        # 对于扁平的人员数据 {name, age...} 这种正则非常有效且鲁棒。
        import re
        # 查找所有被 {} 包裹的内容
        json_objects = re.findall(r'\{[^{}]+\}', content)
        
        for json_str in json_objects:
            try:
                # 尝试解析每一个单独的对象
                obj = json.loads(json_str)
                # 简单的校验：必须包含 name 或 age 才算有效数据
                if "name" in obj or "subject" in obj:
                    final_list.append(obj)
            except:
                # 如果这个对象解析失败（比如断了一半），跳过它，不影响其他数据
                continue
                
        if not final_list:
            # 兜底：如果还不行，打印片段方便调试
            return None, f"解析失败，未提取到有效数据。AI返回片段:\n{content[:200]}"
            
        return final_list, None

    except Exception as e:
        return None, f"执行异常: {str(e)}"

# ==============================================================================
# 3. 页面逻辑控制
# ==============================================================================

if 'data_confirmed' not in st.session_state:
    st.session_state.data_confirmed = False
if 'final_json_str' not in st.session_state:
    st.session_state.final_json_str = "[]"

def reset_app():
    st.session_state.data_confirmed = False
    st.session_state.final_json_str = "[]"
    st.rerun()

# ------------------------------------------------------------------------------
# 页面 A: 数据上传
# ------------------------------------------------------------------------------
if not st.session_state.data_confirmed:
    st.title("🛠️ HKA 师资效能评估 - 智能数据导入")
    
    st.markdown("""
    ### 👋 欢迎使用
    请上传教师花名册（Excel/CSV）。AI 将自动识别并清洗数据。
    **必需信息：** 姓名 | 年龄 | 学科 | 职称 | 学历
    """)
    
    uploaded_file = st.file_uploader("📄 上传文件", type=['xlsx', 'xls', 'csv'])

    if uploaded_file:
        st.divider()
        with st.spinner("🤖 AI 正在清洗数据，请稍候..."):
            try:
                if uploaded_file.name.endswith('.csv'):
                    df = pd.read_csv(uploaded_file)
                else:
                    df = pd.read_excel(uploaded_file)
                
                ai_result, error_msg = ai_parse_excel(df)
                
                if ai_result:
                    st.success(f"✅ 解析成功！共 {len(ai_result)} 条数据。")
                    st.dataframe(pd.DataFrame(ai_result).head(5), use_container_width=True)
                    
                    if st.button("🚀 启动效能大屏", type="primary", use_container_width=True):
                        st.session_state.final_json_str = json.dumps(ai_result, ensure_ascii=False)
                        st.session_state.data_confirmed = True
                        st.rerun()
                else:
                    st.error(f"❌ 解析失败: {error_msg}")
            except Exception as e:
                st.error(f"文件处理错误: {str(e)}")

# ------------------------------------------------------------------------------
# 页面 B: 效能评估大屏
# ------------------------------------------------------------------------------
else:
    with st.sidebar:
        st.info("✅ 数据已加载")
        if st.button("🔄 重新上传"):
            reset_app()

    # HTML 模版
    # 修复3: 移除了 HTML 中 script src 里的 markdown 链接格式
    html_template = r"""
    <!DOCTYPE html>
    <html lang="zh-CN">
    <head>
        <meta charset="UTF-8">
        <meta name="viewport" content="width=device-width, initial-scale=1.0">
        <title>HKA Dashboard</title>
        <!-- 修正 CDN 链接 -->
        <script src="https://cdn.tailwindcss.com"></script>
        <script src="https://cdn.jsdelivr.net/npm/echarts@5.4.3/dist/echarts.min.js"></script>
        <link href="https://cdnjs.cloudflare.com/ajax/libs/font-awesome/6.4.0/css/all.min.css" rel="stylesheet">
        
        <style>
            /* 保持原有样式 */
            @import url('https://fonts.googleapis.com/css2?family=Noto+Sans+SC:wght@300;400;500;700&display=swap');
            body { font-family: 'Noto Sans SC', sans-serif; background-color: #f8fafc; color: #334155; }
            .card { background: white; border-radius: 12px; box-shadow: 0 1px 2px rgba(0,0,0,0.05); border: 1px solid #e2e8f0; }
            input[type=range] { width: 100%; cursor: pointer; }
            
            /* 简单的聊天窗口样式 */
            #chat-wrapper { position: fixed; bottom: 20px; right: 20px; z-index: 50; display: flex; flex-direction: column; align-items: flex-end; }
            #chat-window { width: 350px; height: 500px; background: white; border-radius: 12px; box-shadow: 0 10px 25px rgba(0,0,0,0.1); border: 1px solid #e2e8f0; display: none; flex-direction: column; }
            .chat-bubble { max-width: 85%; padding: 8px 12px; border-radius: 8px; margin-bottom: 8px; font-size: 0.85rem; }
            .chat-bubble.user { background: #3b82f6; color: white; align-self: flex-end; }
            .chat-bubble.ai { background: #f1f5f9; color: #334155; align-self: flex-start; }
            .fab-btn { width: 50px; height: 50px; background: #3b82f6; border-radius: 50%; display: flex; align-items: center; justify-content: center; color: white; cursor: pointer; box-shadow: 0 4px 6px rgba(0,0,0,0.1); }
            
            /* 思考过程样式 */
            details.chat-reasoning { margin-bottom: 5px; background: #fff; border: 1px dashed #ccc; border-radius: 4px; padding: 4px; }
            details.chat-reasoning summary { font-size: 0.75rem; color: #666; cursor: pointer; }
            .chat-reasoning-text { font-size: 0.7rem; color: #888; white-space: pre-wrap; margin-top: 4px; font-family: monospace; }
        </style>
    </head>
    <body class="h-screen flex flex-col overflow-hidden">
        
        <!-- Navbar -->
        <nav class="bg-white border-b border-slate-200 h-14 flex items-center px-6 justify-between shrink-0">
            <div class="font-bold text-slate-700">HKA 师资效能评估 <span class="text-xs text-slate-400 font-normal">AI Pro 2.5</span></div>
            <div class="text-xs text-emerald-600 bg-emerald-50 px-2 py-1 rounded">SiliconFlow AI Connected</div>
        </nav>

        <main class="flex-1 grid grid-cols-12 gap-4 p-4 min-h-0 w-full max-w-[1920px] mx-auto">
            
            <!-- Left Config -->
            <div class="col-span-3 flex flex-col gap-4 overflow-y-auto pr-2">
                <div class="card p-4">
                    <h3 class="font-bold text-sm mb-3 text-slate-700">🎯 模拟招聘控制</h3>
                    <div class="mb-4">
                        <div class="flex justify-between text-xs text-slate-500 mb-1"><span>招聘人数</span> <span id="val-count" class="text-blue-600">0</span></div>
                        <input type="range" id="in-count" min="0" max="50" value="0">
                    </div>
                    <div class="mb-4">
                        <div class="flex justify-between text-xs text-slate-500 mb-1"><span>22-29岁 占比</span> <span id="val-p20">40%</span></div>
                        <input type="range" id="in-p20" min="0" max="100" value="40">
                    </div>
                    <div class="mb-4">
                        <div class="flex justify-between text-xs text-slate-500 mb-1"><span>硕士引进率</span> <span id="val-master">50%</span></div>
                        <input type="range" id="in-master" min="0" max="100" value="50">
                    </div>
                    <div class="p-2 bg-blue-50 text-blue-800 text-xs rounded">
                        <i class="fa-solid fa-info-circle"></i> 调整滑块以模拟引入新教师对整体结构的影响。
                    </div>
                </div>
                
                <div class="card p-4">
                    <h3 class="font-bold text-sm mb-3 text-slate-700">⚙️ 理想模型参数</h3>
                    <div class="mb-2">
                        <div class="flex justify-between text-xs text-slate-500"><span>最佳年龄</span> <span id="val-opt-age">32</span></div>
                        <input type="range" id="opt-age" min="28" max="40" value="32">
                    </div>
                    <div>
                         <div class="flex justify-between text-xs text-slate-500"><span>目标高职率</span> <span id="val-opt-title">30%</span></div>
                        <input type="range" id="opt-title" min="10" max="60" value="30">
                    </div>
                </div>
            </div>

            <!-- Center Charts -->
            <div class="col-span-5 flex flex-col gap-4">
                <!-- TQI Score -->
                <div class="card p-4 flex items-center justify-between h-24">
                    <div>
                        <div class="text-xs text-slate-400 font-bold uppercase">TQI 综合效能指数</div>
                        <div class="text-4xl font-black text-slate-800" id="tqi-score">--</div>
                    </div>
                    <div class="flex-1 ml-8">
                        <div class="h-4 bg-slate-100 rounded-full overflow-hidden">
                            <div id="tqi-bar" class="h-full bg-indigo-500 transition-all duration-500" style="width: 0%"></div>
                        </div>
                    </div>
                </div>

                <!-- Histogram -->
                <div class="card p-4 flex-1 flex flex-col">
                    <h3 class="text-sm font-bold text-slate-700 mb-2">年龄结构分布 (现有 vs 模拟)</h3>
                    <div id="chart-hist" class="flex-1 w-full"></div>
                </div>
                
                <!-- Scatter -->
                <div class="card p-4 h-64 flex flex-col">
                     <h3 class="text-sm font-bold text-slate-700 mb-2">职称-年龄分布</h3>
                     <div id="chart-scatter" class="flex-1 w-full"></div>
                </div>
            </div>

            <!-- Right AI -->
            <div class="col-span-4 flex flex-col gap-4">
                <div class="card p-4 h-64">
                    <h3 class="text-sm font-bold text-slate-700 mb-2">多维雷达图</h3>
                    <div id="chart-radar" class="flex-1 w-full"></div>
                </div>
                
                <div class="card flex-1 p-4 flex flex-col bg-slate-50 border-l-4 border-purple-500">
                    <div class="flex justify-between items-center mb-3">
                        <h3 class="font-bold text-slate-700"><i class="fa-solid fa-robot text-purple-600"></i> AI 诊断报告</h3>
                        <button onclick="runDeepThinking()" id="btn-ai" class="bg-purple-600 text-white text-xs px-3 py-1 rounded hover:bg-purple-700 transition">
                             深度思考 (R1)
                        </button>
                    </div>
                    <div id="ai-report" class="flex-1 overflow-y-auto text-xs text-slate-600 leading-relaxed p-2 bg-white rounded border border-slate-200">
                        点击上方按钮，AI 将根据当前的模拟参数生成深度诊断...
                    </div>
                </div>
            </div>

        </main>

        <!-- Chat Widget -->
        <div id="chat-wrapper">
            <div id="chat-window">
                <div class="bg-slate-800 text-white p-3 text-sm font-bold flex justify-between">
                    <span>效能助手</span>
                    <i class="fa-solid fa-times cursor-pointer" onclick="toggleChat()"></i>
                </div>
                <div id="chat-body" class="flex-1 p-3 overflow-y-auto bg-slate-50 flex flex-col">
                    <div class="chat-bubble ai">您好！我是您的数据助手。</div>
                </div>
                <div class="p-2 bg-white border-t border-slate-200 flex gap-2">
                    <input type="text" id="chat-input" class="flex-1 border border-slate-300 rounded px-2 py-1 text-sm outline-none focus:border-blue-500" placeholder="问点什么...">
                    <button onclick="sendChat()" class="bg-blue-600 text-white px-3 py-1 rounded text-sm">发送</button>
                </div>
            </div>
            <div class="fab-btn" onclick="toggleChat()"><i class="fa-solid fa-comment-dots"></i></div>
        </div>

        <script>
            // 配置注入
            const API_KEY = "[[SILICONFLOW_KEY]]"; // 从 Python 注入
            const API_URL = "https://api.siliconflow.cn/v1/chat/completions"; // 修正 URL

            // 数据注入
            let baseData = [[DATA_INSERT]]; 

            let state = {
                count: 0,
                p20: 40,
                master: 50,
                optAge: 32,
                optTitle: 30
            };

            // ECharts 实例
            let chartHist, chartScatter, chartRadar;

            function init() {
                chartHist = echarts.init(document.getElementById('chart-hist'));
                chartScatter = echarts.init(document.getElementById('chart-scatter'));
                chartRadar = echarts.init(document.getElementById('chart-radar'));

                // 绑定事件
                bindInput('in-count', 'val-count', (v) => state.count = parseInt(v));
                bindInput('in-p20', 'val-p20', (v) => state.p20 = parseInt(v), '%');
                bindInput('in-master', 'val-master', (v) => state.master = parseInt(v), '%');
                bindInput('opt-age', 'val-opt-age', (v) => state.optAge = parseInt(v));
                bindInput('opt-title', 'val-opt-title', (v) => state.optTitle = parseInt(v), '%');

                window.addEventListener('resize', () => {
                    chartHist.resize(); chartScatter.resize(); chartRadar.resize();
                });

                update();
            }

            function bindInput(id, dispId, cb, suffix='') {
                document.getElementById(id).addEventListener('input', (e) => {
                    document.getElementById(dispId).innerText = e.target.value + suffix;
                    cb(e.target.value);
                    update();
                });
            }

            // 核心计算逻辑
            function getSimulatedData() {
                let sim = [];
                if (state.count > 0) {
                    // 简单模拟逻辑
                    const p20Count = Math.round(state.count * (state.p20/100));
                    const others = state.count - p20Count;
                    
                    for(let i=0; i<p20Count; i++) sim.push({ age: 24 + Math.random()*5, edu: Math.random() < state.master/100 ? 2 : 1, titleLevel: 2, isSim: true });
                    for(let i=0; i<others; i++) sim.push({ age: 35 + Math.random()*10, edu: Math.random() < state.master/100 ? 2 : 1, titleLevel: 3, isSim: true });
                }
                return [...baseData, ...sim];
            }

            function update() {
                const data = getSimulatedData();
                const total = data.length;
                if(total === 0) return;

                const avgAge = data.reduce((a,b)=>a+b.age,0) / total;
                const masterRate = data.filter(d=>d.edu===2).length / total * 100;
                const seniorRate = data.filter(d=>d.titleLevel>=4).length / total * 100;

                // TQI 计算 (简化版)
                const sAge = Math.max(0, 100 - Math.abs(avgAge - state.optAge)*5);
                const sTitle = Math.min(100, (seniorRate / state.optTitle) * 100);
                const sEdu = Math.min(100, masterRate * 1.5);
                const tqi = (sAge*0.4 + sTitle*0.3 + sEdu*0.3).toFixed(1);

                document.getElementById('tqi-score').innerText = tqi;
                document.getElementById('tqi-bar').style.width = tqi + '%';

                // Update Charts
                updateCharts(data, avgAge, state.optAge);
            }

            function updateCharts(data, avgAge, optAge) {
                // Histogram
                const bins = ['20-29', '30-39', '40-49', '50+'];
                const existCounts = [0,0,0,0];
                const simCounts = [0,0,0,0];

                data.forEach(d => {
                    let idx = 3;
                    if(d.age < 30) idx=0; else if(d.age < 40) idx=1; else if(d.age < 50) idx=2;
                    
                    if(d.isSim) simCounts[idx]++; else existCounts[idx]++;
                });

                chartHist.setOption({
                    tooltip: { trigger: 'axis' },
                    legend: { data: ['现有','新增'] },
                    xAxis: { data: bins },
                    yAxis: {},
                    series: [
                        { name: '现有', type: 'bar', stack: 'total', data: existCounts, itemStyle: { color: '#94a3b8' } },
                        { name: '新增', type: 'bar', stack: 'total', data: simCounts, itemStyle: { color: '#3b82f6' } }
                    ]
                });

                // Scatter
                const scatterData = data.map(d => [d.age, d.titleLevel + (Math.random()*0.3-0.15)]); // Jitter
                chartScatter.setOption({
                    xAxis: { min: 20, max: 65, name: '年龄' },
                    yAxis: { min: 0, max: 6, name: '职级(1-5)', splitLine:{show:false} },
                    series: [{ type: 'scatter', symbolSize: 5, data: scatterData, itemStyle: { color: (p)=> p.dataIndex >= baseData.length ? '#3b82f6':'#64748b' } }]
                });

                // Radar
                chartRadar.setOption({
                    radar: { indicator: [{name:'年龄结构'}, {name:'高职率'}, {name:'硕士率'}, {name:'梯队分布'}] },
                    series: [{ type: 'radar', data: [{ value: [80, 70, 60, 50], name: '当前状态' }] }]
                });
            }

            // AI Features (R1 for Reasoning)
            async function runDeepThinking() {
                const btn = document.getElementById('btn-ai');
                const report = document.getElementById('ai-report');
                btn.innerText = "R1 深度思考中...";
                btn.disabled = true;
                report.innerHTML = "<div class='text-purple-600 animate-pulse'>正在进行多维度推演...</div>";

                const data = getSimulatedData();
                const metrics = {
                    count: data.length,
                    avgAge: (data.reduce((a,b)=>a+b.age,0)/data.length).toFixed(1),
                    seniorRate: (data.filter(d=>d.titleLevel>=4).length/data.length*100).toFixed(1)
                };

                const prompt = `请分析当前学校师资数据：总人数${metrics.count}，平均年龄${metrics.avgAge}岁，高级职称率${metrics.seniorRate}%。
                对比理想目标（最佳年龄${state.optAge}岁，目标高职率${state.optTitle}%）。
                请给出深度诊断，包含：1. 现状痛点 2. 模拟招聘带来的变化 3. 长期风险。使用HTML格式（无markdown）输出。`;

                try {
                    const resp = await fetch(API_URL, {
                        method: 'POST',
                        headers: { 'Content-Type': 'application/json', 'Authorization': `Bearer ${API_KEY}` },
                        body: JSON.stringify({
                            model: "deepseek-ai/DeepSeek-R1", // 使用 R1
                            messages: [{role: "user", content: prompt}],
                            stream: false // 简单起见，这里演示非流式
                        })
                    });
                    const json = await resp.json();
                    let content = json.choices[0].message.content;
                    // 清理 <think> 标签以便展示最终结果 (或者你可以选择展示思考过程)
                    content = content.replace(/<think>[\s\S]*?<\/think>/g, "<div class='text-xs text-slate-400 mb-2 border-b pb-2'>[已完成深度思考]</div>");
                    report.innerHTML = content.replace(/```html/g, '').replace(/```/g, '');
                } catch(e) {
                    report.innerText = "AI 调用失败: " + e.message;
                }
                btn.innerText = "深度思考 (R1)";
                btn.disabled = false;
            }

            // Chat with R1
            function toggleChat() {
                const win = document.getElementById('chat-window');
                win.style.display = win.style.display === 'flex' ? 'none' : 'flex';
            }

            async function sendChat() {
                const inp = document.getElementById('chat-input');
                const val = inp.value;
                if(!val) return;
                
                const body = document.getElementById('chat-body');
                body.innerHTML += `<div class="chat-bubble user">${val}</div>`;
                inp.value = '';

                // Add loading placeholder
                const loadId = 'msg-' + Date.now();
                body.innerHTML += `<div id="${loadId}" class="chat-bubble ai">...</div>`;
                body.scrollTop = body.scrollHeight;

                try {
                    const resp = await fetch(API_URL, {
                        method: 'POST',
                        headers: { 'Content-Type': 'application/json', 'Authorization': `Bearer ${API_KEY}` },
                        body: JSON.stringify({
                            model: "deepseek-ai/DeepSeek-R1",
                            messages: [{role: "user", content: val}],
                            stream: true
                        })
                    });

                    const reader = resp.body.getReader();
                    const decoder = new TextDecoder();
                    let buffer = '';
                    let finalContent = '';
                    let reasoningContent = '';
                    
                    const bubble = document.getElementById(loadId);
                    bubble.innerHTML = ''; // Clear loading

                    // 创建思考折叠区和内容区
                    let details = document.createElement('details');
                    details.className = 'chat-reasoning';
                    details.innerHTML = `<summary>AI 正在思考...</summary><div class="chat-reasoning-text"></div>`;
                    bubble.appendChild(details);
                    let contentDiv = document.createElement('div');
                    bubble.appendChild(contentDiv);
                    
                    const reasonTextDiv = details.querySelector('.chat-reasoning-text');

                    while (true) {
                        const { done, value } = await reader.read();
                        if (done) break;
                        buffer += decoder.decode(value, { stream: true });
                        const lines = buffer.split('\n');
                        buffer = lines.pop();

                        for (const line of lines) {
                            if (line.startsWith('data: ')) {
                                const jsonStr = line.slice(6);
                                if (jsonStr === '[DONE]') continue;
                                try {
                                    const json = JSON.parse(jsonStr);
                                    const delta = json.choices[0].delta;
                                    
                                    if (delta.reasoning_content) {
                                        reasoningContent += delta.reasoning_content;
                                        reasonTextDiv.innerText = reasoningContent;
                                    }
                                    if (delta.content) {
                                        finalContent += delta.content;
                                        contentDiv.innerHTML = finalContent.replace(/\n/g, '<br>');
                                        details.querySelector('summary').innerText = "已深度思考";
                                    }
                                } catch(e) {}
                            }
                        }
                        body.scrollTop = body.scrollHeight;
                    }
                    if(!reasoningContent) details.style.display = 'none';

                } catch(e) {
                    document.getElementById(loadId).innerText = "Error: " + e.message;
                }
            }

            // Init
            setTimeout(init, 500);
        </script>
    </body>
    </html>
    """
    
    # 注入数据和 Key
    html_content = html_template.replace("[[SILICONFLOW_KEY]]", API_KEY)
    html_content = html_content.replace("[[DATA_INSERT]]", st.session_state.final_json_str)
    
    components.html(html_content, height=850, scrolling=False)
