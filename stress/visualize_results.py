#!/usr/bin/env python3
"""Generate presentation-quality visualizations from stress test results."""

import pandas as pd
import matplotlib.pyplot as plt
import matplotlib.dates as mdates
from pathlib import Path
from datetime import datetime

# 中文字体配置
plt.rcParams['font.sans-serif'] = ['Microsoft YaHei', 'SimHei', 'Arial Unicode MS']
plt.rcParams['axes.unicode_minus'] = False

RESULTS_DIR = Path(__file__).parent / "results"
OUTPUT_DIR = Path(__file__).parent / "visualizations"
OUTPUT_DIR.mkdir(exist_ok=True)

# 柔和配色方案
COLORS = {
    'throughput': '#5fa777',  # 绿
    'latency': '#6ba3d4',     # 蓝
    'failures': '#c47b9e',    # 紫红
    'bg': '#f5f1e8',          # 米黄背景
}


def load_history(scenario: str) -> pd.DataFrame:
    """Load Locust stats_history CSV."""
    csv_path = RESULTS_DIR / f"{scenario}_stats_history.csv"
    if not csv_path.exists():
        raise FileNotFoundError(f"Missing {csv_path}")

    df = pd.read_csv(csv_path)
    df = df[df['Name'] == 'Aggregated'].copy()  # Aggregated rows only
    df['time'] = pd.to_datetime(df['Timestamp'], unit='s')
    # Replace 'N/A' strings with NaN
    for col in ['50%', '66%', '75%', '80%', '90%', '95%', '98%', '99%', '99.9%', '99.99%', '100%']:
        df[col] = pd.to_numeric(df[col], errors='coerce')
    return df


def chart_spike_recovery():
    """S10: 尖峰冲击与自愈 — 时序图 + 摘要表."""
    df = load_history('s10_spike')

    # 找到并发量变化的转折点
    # 0-10s: 10→200, 保持到约120s, 然后回落
    spike_start = df[df['User Count'] >= 190].iloc[0]['time'] if len(df[df['User Count'] >= 190]) > 0 else None
    recovery_start = df.iloc[-60:].iloc[0]['time'] if len(df) > 60 else None  # 最后60秒

    fig, (ax1, ax_table) = plt.subplots(2, 1, figsize=(12, 8),
                                         gridspec_kw={'height_ratios': [3, 1]},
                                         facecolor=COLORS['bg'])

    # === 时序图 ===
    ax1.set_facecolor(COLORS['bg'])

    # 左轴: 吞吐 + 失败
    ax1_twin = ax1.twinx()

    line1 = ax1.plot(df['time'], df['Requests/s'],
                     color=COLORS['throughput'], linewidth=1.8, label='吞吐 (rps)')
    line2 = ax1.plot(df['time'], df['Failures/s'],
                     color=COLORS['failures'], linewidth=1.8, label='失败/s')

    # 右轴: p95 延迟
    line3 = ax1_twin.plot(df['time'], df['95%'],
                          color=COLORS['latency'], linewidth=1.8, alpha=0.7, label='p95 延迟 (ms)')

    # 标注区域
    if spike_start:
        ax1.axvline(spike_start, color='#d4a574', linestyle='--', linewidth=1, alpha=0.6)
        ax1.text(spike_start, ax1.get_ylim()[1] * 0.9, ' 冲击开始',
                fontsize=9, color='#8b6f47', va='top')
    if recovery_start:
        ax1.axvline(recovery_start, color='#7ba36f', linestyle='--', linewidth=1, alpha=0.6)
        ax1.text(recovery_start, ax1.get_ylim()[1] * 0.9, ' 回落',
                fontsize=9, color='#4a6b3e', va='top')

    ax1.set_xlabel('时间', fontsize=11)
    ax1.set_ylabel('请求速率', fontsize=11, color=COLORS['throughput'])
    ax1_twin.set_ylabel('p95 延迟 (ms)', fontsize=11, color=COLORS['latency'])
    ax1.tick_params(axis='y', labelcolor=COLORS['throughput'])
    ax1_twin.tick_params(axis='y', labelcolor=COLORS['latency'])
    ax1.grid(axis='y', alpha=0.2, color='#8b7355')

    # 合并图例
    lines = line1 + line2 + line3
    labels = [l.get_label() for l in lines]
    ax1.legend(lines, labels, loc='upper left', frameon=False, fontsize=10)

    ax1.set_title('S10: 尖峰冲击与自愈 (10→200并发)',
                  fontsize=14, pad=15, color='#5a4a3a')

    # === 摘要表 ===
    ax_table.axis('tight')
    ax_table.axis('off')

    # 计算汇总数据
    spike_phase = df[df['User Count'] >= 190]
    recovery_phase = df.iloc[-60:] if len(df) > 60 else df.iloc[-30:]

    total_requests = df['Total Request Count'].iloc[-1]
    total_failures = df['Total Failure Count'].iloc[-1]
    failure_rate = f"{100 * total_failures / total_requests:.1f}%" if total_requests > 0 else "0%"
    avg_throughput_spike = spike_phase['Requests/s'].mean() if len(spike_phase) > 0 else 0
    p95_spike = spike_phase['95%'].quantile(0.95) if len(spike_phase) > 0 else 0
    p99_spike = spike_phase['99%'].quantile(0.95) if len(spike_phase) > 0 else 0
    recovery_time = "~75秒"  # 来自报告

    table_data = [
        ['完整迭代次数', '峰值吞吐', 'p95响应时间', 'P99响应时间'],
        [f'{total_requests}次', f'{avg_throughput_spike:.1f}次/s',
         f'{p95_spike/1000:.1f}s', f'{p99_spike/1000:.1f}s']
    ]

    table = ax_table.table(cellText=table_data, cellLoc='center', loc='center',
                           bbox=[0.05, 0.2, 0.9, 0.6])
    table.auto_set_font_size(False)
    table.set_fontsize(11)

    for i in range(4):
        table[(0, i)].set_facecolor('#d4c4a8')
        table[(0, i)].set_text_props(weight='bold', color='#3a2a1a')
        table[(1, i)].set_facecolor('#ebe5d9')

    for key, cell in table.get_celld().items():
        cell.set_linewidth(1.5)
        cell.set_edgecolor('#8b7355')

    # 场景说明
    ax_table.text(0.5, 0.05,
                  '10→200 并发（10秒内拉起），保持 2 分钟后回落。失败率 3.9%，吞吐与延迟在回落后 75 秒内完全恢复。',
                  ha='center', fontsize=10, color='#6a5a4a', style='italic',
                  bbox=dict(boxstyle='round,pad=0.5', facecolor='#ebe5d9', edgecolor='#8b7355', linewidth=1))

    plt.tight_layout()
    output_path = OUTPUT_DIR / 's10_spike_recovery.png'
    plt.savefig(output_path, dpi=150, bbox_inches='tight', facecolor=COLORS['bg'])
    print(f"[OK] {output_path}")
    plt.close()


def chart_ladder_plateau():
    """S1: 阶梯加压 — 吞吐平台期."""
    # 手动汇总各档数据（从报告中提取）
    ladder_data = {
        'concurrency': [10, 30, 60, 120, 180, 240],
        'throughput': [26.8, 28.2, 25.8, 28.5, 27.1, 29.3],  # rps
        'p95': [380, 520, 9200, 23000, 28000, 31000],  # ms
        'error_rate': [0, 0, 0, 5.2, 8.1, 11.3],  # %
    }

    df = pd.DataFrame(ladder_data)

    fig, (ax1, ax2) = plt.subplots(1, 2, figsize=(14, 5), facecolor=COLORS['bg'])

    # === 左图: 吞吐平台期 ===
    ax1.set_facecolor(COLORS['bg'])
    ax1.plot(df['concurrency'], df['throughput'],
             marker='o', markersize=8, linewidth=2.5,
             color=COLORS['throughput'], label='吞吐 (rps)')
    ax1.axhline(y=27, color='#d4a574', linestyle='--', linewidth=1.5, alpha=0.6, label='平台期 (~27 rps)')
    ax1.fill_between(df['concurrency'], 25, 30, alpha=0.15, color=COLORS['throughput'])

    ax1.set_xlabel('并发数', fontsize=12)
    ax1.set_ylabel('吞吐 (请求/秒)', fontsize=12)
    ax1.set_title('吞吐平台期：N=10 到 N=240 稳定在 26-29 rps', fontsize=13, color='#5a4a3a', pad=12)
    ax1.legend(frameon=False, fontsize=10)
    ax1.grid(axis='y', alpha=0.2, color='#8b7355')
    ax1.set_xticks(df['concurrency'])

    # === 右图: 错误率 ===
    ax2.set_facecolor(COLORS['bg'])
    bars = ax2.bar(df['concurrency'], df['error_rate'],
                   color=COLORS['failures'], alpha=0.75, width=20)
    ax2.axhline(y=1, color='#c47b9e', linestyle='--', linewidth=1, alpha=0.5, label='1% 阈值')

    # 标注 N≥120 起出现错误
    ax2.axvline(x=115, color='#d4a574', linestyle=':', linewidth=1.5, alpha=0.6)
    ax2.text(115, ax2.get_ylim()[1] * 0.9, ' N≥120 起出现 5xx',
            fontsize=9, color='#8b6f47', ha='right', va='top')

    ax2.set_xlabel('并发数', fontsize=12)
    ax2.set_ylabel('错误率 (%)', fontsize=12)
    ax2.set_title('错误率：N≥120 时连接池耗尽 (已修复 D5)', fontsize=13, color='#5a4a3a', pad=12)
    ax2.legend(frameon=False, fontsize=10)
    ax2.grid(axis='y', alpha=0.2, color='#8b7355')
    ax2.set_xticks(df['concurrency'])

    plt.tight_layout()
    output_path = OUTPUT_DIR / 's1_ladder_plateau.png'
    plt.savefig(output_path, dpi=150, bbox_inches='tight', facecolor=COLORS['bg'])
    print(f"[OK] {output_path}")
    plt.close()


def chart_workspace_lock_comparison():
    """H1: Workspace 行锁对照实验."""
    data = {
        '分组': ['共享热点', '隔离 workspace'],
        'push p50 (ms)': [3742, 4578],
        '吞吐 (rps)': [7.07, 5.55],
    }
    df = pd.DataFrame(data)

    fig, (ax1, ax2) = plt.subplots(1, 2, figsize=(12, 5), facecolor=COLORS['bg'])

    x_pos = range(len(df))

    # === 左图: p50 ===
    ax1.set_facecolor(COLORS['bg'])
    bars1 = ax1.bar(x_pos, df['push p50 (ms)'],
                    color=[COLORS['latency'], '#a3c4e4'], alpha=0.8, width=0.5)
    ax1.set_ylabel('push p50 延迟 (ms)', fontsize=12)
    ax1.set_title('反直觉结果：共享热点更快', fontsize=13, color='#5a4a3a', pad=12)
    ax1.set_xticks(x_pos)
    ax1.set_xticklabels(df['分组'], fontsize=11)
    ax1.grid(axis='y', alpha=0.2, color='#8b7355')

    for i, (bar, val) in enumerate(zip(bars1, df['push p50 (ms)'])):
        ax1.text(bar.get_x() + bar.get_width()/2, val + 100,
                f'{val} ms', ha='center', fontsize=11, weight='bold')

    # === 右图: 吞吐 ===
    ax2.set_facecolor(COLORS['bg'])
    bars2 = ax2.bar(x_pos, df['吞吐 (rps)'],
                    color=[COLORS['throughput'], '#8fc4a0'], alpha=0.8, width=0.5)
    ax2.set_ylabel('吞吐 (请求/秒)', fontsize=12)
    ax2.set_title('隔离后吞吐反而下降 21%', fontsize=13, color='#5a4a3a', pad=12)
    ax2.set_xticks(x_pos)
    ax2.set_xticklabels(df['分组'], fontsize=11)
    ax2.grid(axis='y', alpha=0.2, color='#8b7355')

    for i, (bar, val) in enumerate(zip(bars2, df['吞吐 (rps)'])):
        ax2.text(bar.get_x() + bar.get_width()/2, val + 0.15,
                f'{val} rps', ha='center', fontsize=11, weight='bold')

    fig.text(0.5, 0.02,
            '结论：该并发下行锁实际起到准入控制作用，天花板是 CPU (153.6% / 150%)，不是锁',
            ha='center', fontsize=11, color='#6a5a4a', style='italic',
            bbox=dict(boxstyle='round,pad=0.6', facecolor='#ebe5d9', edgecolor='#8b7355', linewidth=1.5))

    plt.tight_layout(rect=[0, 0.06, 1, 1])
    output_path = OUTPUT_DIR / 'h1_workspace_lock.png'
    plt.savefig(output_path, dpi=150, bbox_inches='tight', facecolor=COLORS['bg'])
    print(f"[OK] {output_path}")
    plt.close()


if __name__ == '__main__':
    print("生成压力测试可视化图表...")
    chart_spike_recovery()
    chart_ladder_plateau()
    chart_workspace_lock_comparison()
    print(f"\n全部图表已保存至 {OUTPUT_DIR}/")
