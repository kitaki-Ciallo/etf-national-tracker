/**
 * ETF 国家队量化看板 — 主页逻辑
 */
(function () {
    'use strict';

    let chartInstance = null;
    let tableData = [];
    let currentSort = { key: 'nt_hold_ratio', dir: 'desc' };

    // ─── Init ───
    document.addEventListener('DOMContentLoaded', () => {
        initChart();
        loadChartData(365);
        loadTableData();
        initTimeSelector();
        initTableSort();
    });

    // ─── Time Selector ───
    function initTimeSelector() {
        document.querySelectorAll('.time-btn').forEach(btn => {
            btn.addEventListener('click', () => {
                document.querySelectorAll('.time-btn').forEach(b => b.classList.remove('active'));
                btn.classList.add('active');
                loadChartData(parseInt(btn.dataset.days));
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
