/**
 * ETF 国家队量化看板 — 主页逻辑
 */
(function () {
    'use strict';

    let chartInstance = null;
    let flowChartInstance = null;
    let tableData = [];
    let currentSort = { key: 'nt_hold_ratio', dir: 'desc' };

    // ─── Init ───
    document.addEventListener('DOMContentLoaded', () => {
        initChart();
        initFlowChart();
        loadChartData(365);
        loadFlowChartData(365);
        loadTableData();
        initTimeSelector();
        initFlowTimeSelector();
        initTableSort();
    });

    // ─── Time Selector ───
    function initTimeSelector() {
        document.querySelectorAll('#timeSelector .time-btn').forEach(btn => {
            btn.addEventListener('click', () => {
                document.querySelectorAll('#timeSelector .time-btn').forEach(b => b.classList.remove('active'));
                btn.classList.add('active');
                loadChartData(parseInt(btn.dataset.days));
            });
        });
    }

    function initFlowTimeSelector() {
        document.querySelectorAll('#flowTimeSelector .time-btn').forEach(btn => {
            btn.addEventListener('click', () => {
                document.querySelectorAll('#flowTimeSelector .time-btn').forEach(b => b.classList.remove('active'));
                btn.classList.add('active');
                loadFlowChartData(parseInt(btn.dataset.days));
            });
        });
    }

    // ─── ECharts Init ───
    function initChart() {
        const el = document.getElementById('mainChart');
        el.innerHTML = '';
        chartInstance = echarts.init(el, null, { renderer: 'canvas' });
        window.addEventListener('resize', () => chartInstance && chartInstance.resize());
    }

    // ─── Load Chart Data ───
    async function loadChartData(days) {
        try {
            const res = await fetch(`/api/overview/chart?days=${days}`);
            const data = await res.json();
            renderChart(data);
        } catch (e) {
            console.error('Chart load error:', e);
        }
    }

    // ─── Render Chart ───
    function renderChart(data) {
        const shareDates = data.share_total.map(d => d.date);
        const shareValues = data.share_total.map(d => (d.total / 1e8).toFixed(2));

        const series = [{
            name: '国家队ETF总份额(亿份)',
            type: 'line',
            yAxisIndex: 0,
            data: shareValues,
            smooth: true,
            showSymbol: false,
            lineStyle: { width: 2.5, color: '#6366f1' },
            areaStyle: {
                color: {
                    type: 'linear', x: 0, y: 0, x2: 0, y2: 1,
                    colorStops: [
                        { offset: 0, color: 'rgba(99,102,241,0.25)' },
                        { offset: 1, color: 'rgba(99,102,241,0.02)' }
                    ]
                }
            },
            z: 10,
        }];

        const colors = ['#06b6d4', '#f59e0b', '#ec4899'];
        let ci = 0;
        const legendData = ['国家队ETF总份额(亿份)'];

        for (const [code, info] of Object.entries(data.index_prices)) {
            const c = colors[ci++ % colors.length];
            const priceDates = info.data.map(d => d.date);
            const priceValues = info.data.map(d => d.close);
            legendData.push(info.name);
            series.push({
                name: info.name,
                type: 'line',
                yAxisIndex: 1,
                data: priceValues,
                smooth: true,
                showSymbol: false,
                lineStyle: { width: 1.8, color: c },
                z: 5,
            });
        }

        chartInstance.setOption({
            backgroundColor: 'transparent',
            tooltip: {
                trigger: 'axis',
                backgroundColor: 'rgba(17,24,39,0.95)',
                borderColor: 'rgba(99,102,241,0.3)',
                textStyle: { color: '#f1f5f9', fontSize: 12 },
                axisPointer: { type: 'cross', crossStyle: { color: '#64748b' } },
            },
            legend: {
                data: legendData,
                top: 4,
                textStyle: { color: '#94a3b8', fontSize: 11 },
                icon: 'roundRect',
                itemWidth: 14, itemHeight: 3,
            },
            grid: { left: 80, right: 80, top: 50, bottom: 40 },
            xAxis: {
                type: 'category',
                data: shareDates,
                axisLine: { lineStyle: { color: 'rgba(255,255,255,0.06)' } },
                axisLabel: { color: '#64748b', fontSize: 10 },
                axisTick: { show: false },
            },
            yAxis: [
                {
                    type: 'value',
                    name: '总份额(亿份)',
                    nameTextStyle: { color: '#64748b', fontSize: 10 },
                    axisLabel: { color: '#64748b', fontSize: 10, formatter: '{value}' },
                    splitLine: { lineStyle: { color: 'rgba(255,255,255,0.04)' } },
                    axisLine: { show: false },
                },
                {
                    type: 'value',
                    name: '价格(元)',
                    nameTextStyle: { color: '#64748b', fontSize: 10 },
                    axisLabel: { color: '#64748b', fontSize: 10 },
                    splitLine: { show: false },
                    axisLine: { show: false },
                }
            ],
            dataZoom: [{ type: 'inside', start: 0, end: 100 }],
            series: series,
        }, true);
    }

    // ─── Flow Chart Init ───
    function initFlowChart() {
        const el = document.getElementById('flowChart');
        if(!el) return;
        el.innerHTML = '';
        flowChartInstance = echarts.init(el, null, { renderer: 'canvas' });
        window.addEventListener('resize', () => flowChartInstance && flowChartInstance.resize());
    }

    // ─── Load Flow Chart Data ───
    async function loadFlowChartData(days) {
        try {
            const res = await fetch(`/api/capital_flow?days=${days}`);
            const data = await res.json();
            renderFlowChart(data);
        } catch (e) {
            console.error('Flow chart load error:', e);
        }
    }

    // ─── Render Flow Chart ───
    function renderFlowChart(data) {
        if (!flowChartInstance) return;
        const dates = data.dates;
        const seriesData = [];
        
        // 我们需要把正数变红，负数变绿
        // 在 ECharts 中，可以通过 itemStyle 根据数据正负动态设置颜色
        const getColors = (val) => val >= 0 ? 'rgba(239, 68, 68, 0.8)' : 'rgba(34, 197, 94, 0.8)';

        for (const [name, values] of Object.entries(data.series)) {
            const isTotal = name === '总计';
            seriesData.push({
                name: name,
                type: 'bar',
                barMaxWidth: 30,
                // 把“总计”放一个组，其他指数放另一个组，这样就不会叠加混乱
                stack: isTotal ? 'total' : 'index',
                data: values.map(v => ({
                    value: v,
                    itemStyle: {
                        color: getColors(v),
                        opacity: isTotal ? 1 : 0.6
                    }
                })),
                label: {
                    show: false
                }
            });
        }

        flowChartInstance.setOption({
            backgroundColor: 'transparent',
            tooltip: {
                trigger: 'axis',
                axisPointer: { type: 'shadow' },
                backgroundColor: 'rgba(15, 23, 42, 0.9)',
                borderColor: 'rgba(255,255,255,0.1)',
                textStyle: { color: '#f8fafc' },
                valueFormatter: (value) => value + ' 亿元'
            },
            legend: {
                top: 5,
                left: 'center',
                textStyle: { color: '#94a3b8', fontSize: 12 },
                itemWidth: 12,
                itemHeight: 12,
                // 默认只选中总计，不然柱子太多
                selected: {
                    '总计': true,
                    '上证180': false,
                    '中证1000': false,
                    '沪深300': false,
                    '中证500': false,
                    '科创50': false,
                    '上证50': false,
                    '其他': false
                }
            },
            grid: { top: 40, left: '5%', right: '5%', bottom: '10%', containLabel: true },
            xAxis: {
                type: 'category',
                data: dates,
                axisLine: { lineStyle: { color: 'rgba(255,255,255,0.06)' } },
                axisLabel: { color: '#64748b', fontSize: 10 },
                axisTick: { show: false },
            },
            yAxis: {
                type: 'value',
                name: '资金净流入 (亿元)',
                nameTextStyle: { color: '#64748b', fontSize: 10 },
                axisLabel: { color: '#64748b', fontSize: 10, formatter: '{value}' },
                splitLine: { lineStyle: { color: 'rgba(255,255,255,0.04)' } },
                axisLine: { show: false },
            },
            dataZoom: [{ type: 'inside', start: 0, end: 100 }],
            series: seriesData,
        }, true);
    }

    // ─── Load Table ───
    async function loadTableData() {
        try {
            const res = await fetch('/api/overview/table');
            const json = await res.json();
            tableData = json.data || json;
            const shareDate = json.latest_share_date || '-';
            document.getElementById('shareUpdateDate').innerHTML =
                `📅 份额数据更新至: <span class="date-value">${shareDate}</span>`;
            document.getElementById('lastUpdate').textContent =
                `共 ${tableData.length} 只国家队持仓 ETF`;
            document.getElementById('etfCount').textContent = `${tableData.length} 只`;
            sortAndRender();
        } catch (e) {
            document.getElementById('etfTableBody').innerHTML =
                '<tr><td colspan="11" class="no-data">数据加载失败, 请检查后端服务</td></tr>';
        }
    }

    // ─── Table Sort ───
    function initTableSort() {
        document.querySelectorAll('#etfTable thead th[data-sort]').forEach(th => {
            th.addEventListener('click', () => {
                const key = th.dataset.sort;
                if (currentSort.key === key) {
                    currentSort.dir = currentSort.dir === 'asc' ? 'desc' : 'asc';
                } else {
                    currentSort = { key, dir: 'desc' };
                }
                sortAndRender();
                // Update header indicators
                document.querySelectorAll('#etfTable thead th').forEach(h => {
                    h.classList.remove('sorted-asc', 'sorted-desc');
                });
                th.classList.add(currentSort.dir === 'asc' ? 'sorted-asc' : 'sorted-desc');
            });
        });
    }

    function sortAndRender() {
        const { key, dir } = currentSort;
        tableData.sort((a, b) => {
            let va = a[key], vb = b[key];
            if (va == null) return 1;
            if (vb == null) return -1;
            if (typeof va === 'string') return dir === 'asc' ? va.localeCompare(vb) : vb.localeCompare(va);
            return dir === 'asc' ? va - vb : vb - va;
        });
        renderTable();
    }

    // ─── Render Table ───
    function renderTable() {
        const tbody = document.getElementById('etfTableBody');
        if (!tableData.length) {
            tbody.innerHTML = '<tr><td colspan="11" class="no-data">暂无数据</td></tr>';
            return;
        }

        tbody.innerHTML = tableData.map(row => {
            const shareB = (row.latest_share / 1e8).toFixed(2);
            return `<tr onclick="location.href='/detail/${row.ts_code}'" title="点击查看详情">
                <td>${row.ts_code}</td>
                <td class="name-col">${row.name || ''}</td>
                <td>${shareB}</td>
                ${chgCell(row.share_chg_1d)}
                ${chgCell(row.share_chg_1w)}
                ${chgCell(row.share_chg_1m)}
                ${chgCell(row.share_chg_3m)}
                ${chgCell(row.share_chg_1y)}
                <td><span class="badge badge-nt">${(row.nt_hold_ratio || 0).toFixed(2)}%</span></td>
                <td>${ntChangeCell(row)}</td>
                <td style="font-size:0.75rem;color:var(--text-muted)">
                    ${row.latest_report_date || '-'}<br>${row.prev_report_date || '-'}
                </td>
            </tr>`;
        }).join('');
    }

    function chgCell(val) {
        if (val == null) return '<td class="val-neutral">-</td>';
        const cls = val > 0 ? 'val-up' : val < 0 ? 'val-down' : 'val-neutral';
        const sign = val > 0 ? '+' : '';
        return `<td class="${cls}">${sign}${val.toFixed(2)}%</td>`;
    }

    function ntChangeCell(row) {
        if (row.nt_is_new) return '<span class="badge badge-new">✨ 新进</span>';
        if (row.nt_hold_change == null) return '<span class="val-neutral">-</span>';
        const v = row.nt_hold_change;
        const cls = v > 0 ? 'val-up' : v < 0 ? 'val-down' : 'val-neutral';
        const sign = v > 0 ? '+' : '';
        return `<span class="${cls}">${sign}${v.toFixed(2)}%</span>`;
    }
})();
