/**
 * ETF 国家队量化看板 — 详情页逻辑
 */
(function () {
    'use strict';

    let chartInstance = null;
    let cachedData = null;

    // 从 URL 提取 ETF 代码
    const tsCode = window.location.pathname.split('/').pop();

    document.addEventListener('DOMContentLoaded', () => {
        document.title = `${tsCode} — ETF 详情`;
        document.getElementById('etfCode').textContent = tsCode;
        initChart();
        loadData(365);
        initTimeSelector();
    });

    function initTimeSelector() {
        document.querySelectorAll('.time-btn').forEach(btn => {
            btn.addEventListener('click', () => {
                document.querySelectorAll('.time-btn').forEach(b => b.classList.remove('active'));
                btn.classList.add('active');
                loadData(parseInt(btn.dataset.days));
            });
        });
    }

    function initChart() {
        const el = document.getElementById('detailChart');
        el.innerHTML = '';
        chartInstance = echarts.init(el, null, { renderer: 'canvas' });
        window.addEventListener('resize', () => chartInstance && chartInstance.resize());
    }

    async function loadData(days) {
        try {
            const res = await fetch(`/api/detail/${tsCode}?days=${days}`);
            const data = await res.json();
            if (data.error) {
                document.getElementById('etfName').textContent = '未找到该 ETF';
                return;
            }
            cachedData = data;
            document.getElementById('etfName').textContent = data.info.name;
            document.title = `${tsCode} ${data.info.name} — ETF 详情`;
            renderChart(data);
            renderHolders(data);
        } catch (e) {
            console.error('Load error:', e);
        }
    }

    function renderChart(data) {
        const priceDates = data.prices.map(d => d.date);
        const priceValues = data.prices.map(d => d.close);
        const shareDates = data.shares.map(d => d.date);
        const shareValues = data.shares.map(d => (d.total_share / 1e8).toFixed(2));

        // 合并日期轴
        const allDates = [...new Set([...priceDates, ...shareDates])].sort();

        // 对齐数据
        const priceMap = {}; data.prices.forEach(d => priceMap[d.date] = d.close);
        const shareMap = {}; data.shares.forEach(d => shareMap[d.date] = (d.total_share / 1e8).toFixed(2));
        const alignedPrices = allDates.map(d => priceMap[d] || null);
        const alignedShares = allDates.map(d => shareMap[d] || null);

        chartInstance.setOption({
            backgroundColor: 'transparent',
            tooltip: {
                trigger: 'axis',
                backgroundColor: 'rgba(17,24,39,0.95)',
                borderColor: 'rgba(99,102,241,0.3)',
                textStyle: { color: '#f1f5f9', fontSize: 12 },
            },
            legend: {
                data: ['收盘价', '总份额(亿份)'],
                top: 4,
                textStyle: { color: '#94a3b8', fontSize: 11 },
                icon: 'roundRect', itemWidth: 14, itemHeight: 3,
            },
            grid: { left: 70, right: 80, top: 50, bottom: 40 },
            xAxis: {
                type: 'category', data: allDates,
                axisLine: { lineStyle: { color: 'rgba(255,255,255,0.06)' } },
                axisLabel: { color: '#64748b', fontSize: 10 },
                axisTick: { show: false },
            },
            yAxis: [
                {
                    type: 'value', name: '价格(元)',
                    nameTextStyle: { color: '#64748b', fontSize: 10 },
                    axisLabel: { color: '#64748b', fontSize: 10 },
                    splitLine: { lineStyle: { color: 'rgba(255,255,255,0.04)' } },
                    axisLine: { show: false },
                },
                {
                    type: 'value', name: '份额(亿份)',
                    nameTextStyle: { color: '#64748b', fontSize: 10 },
                    axisLabel: { color: '#64748b', fontSize: 10 },
                    splitLine: { show: false },
                    axisLine: { show: false },
                },
            ],
            dataZoom: [{ type: 'inside', start: 0, end: 100 }],
            series: [
                {
                    name: '收盘价', type: 'line', yAxisIndex: 0,
                    data: alignedPrices, smooth: true, showSymbol: false,
                    lineStyle: { width: 2, color: '#06b6d4' },
                    z: 10,
                },
                {
                    name: '总份额(亿份)', type: 'line', yAxisIndex: 1,
                    data: alignedShares, smooth: true, showSymbol: false,
                    lineStyle: { width: 2, color: '#8b5cf6' },
                    areaStyle: {
                        color: {
                            type: 'linear', x: 0, y: 0, x2: 0, y2: 1,
                            colorStops: [
                                { offset: 0, color: 'rgba(139,92,246,0.2)' },
                                { offset: 1, color: 'rgba(139,92,246,0.01)' },
                            ],
                        },
                    },
                    z: 5,
                },
            ],
        }, true);
    }

    function renderHolders(data) {
        // Report dates
        const rdEl = document.getElementById('reportDates');
        rdEl.innerHTML = `
            <span>📅 最新报告期: <strong>${data.latest_report_date || '-'}</strong></span>
            <span>📅 上期报告期: <strong>${data.prev_report_date || '-'}</strong></span>
        `;

        // Build prev map
        const prevMap = {};
        if (data.holders_prev) {
            data.holders_prev.forEach(h => {
                prevMap[h.holder_name] = h;
            });
        }

        const tbody = document.getElementById('holdersBody');
        if (!data.holders_latest || !data.holders_latest.length) {
            tbody.innerHTML = '<tr><td colspan="7" class="no-data">暂无持有人数据</td></tr>';
            return;
        }

        tbody.innerHTML = data.holders_latest.map((h, i) => {
            const prev = prevMap[h.holder_name];
            const prevAmt = prev ? (prev.hold_amount / 1e4).toFixed(2) : '-';
            const prevRatio = prev ? prev.hold_ratio.toFixed(2) : '-';
            const change = prev && prev.hold_amount > 0
                ? ((h.hold_amount - prev.hold_amount) / prev.hold_amount * 100).toFixed(2)
                : '新进';
            const changeCls = change === '新进' ? '' :
                parseFloat(change) > 0 ? 'val-up' : parseFloat(change) < 0 ? 'val-down' : 'val-neutral';
            const changeDisplay = change === '新进' ?
                '<span class="badge badge-new">✨ 新进</span>' :
                `<span class="${changeCls}">${parseFloat(change) > 0 ? '+' : ''}${change}%</span>`;
            const rowCls = h.is_nt ? 'nt-highlight' : '';

            return `<tr class="${rowCls}">
                <td>${i + 1}</td>
                <td class="holder-name" title="${h.holder_name}">
                    ${h.holder_name}
                    ${h.is_nt ? '<span class="badge badge-nt" style="margin-left:6px">国家队</span>' : ''}
                </td>
                <td>${(h.hold_amount / 1e4).toFixed(2)}</td>
                <td>${h.hold_ratio.toFixed(2)}</td>
                <td>${prevAmt}</td>
                <td>${prevRatio}</td>
                <td>${changeDisplay}</td>
            </tr>`;
        }).join('');
    }
})();
