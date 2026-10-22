"""python -m satellite_diagnosis ..."""
from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path
from .data import read_table, load_case
from .diagnosis import analyze_case
from .graph import MCPGraph, LocalGraph, import_graph

DEFAULT_DATA = Path(__file__).resolve().parents[2] / 'data-output' / 'satellite_demo_v1'


def text_report(r:dict) -> str:
    lines=[f"案例 {r['case_id']} | 截止 {r['as_of']} | 图后端 {r['graph_backend']}",
           f"1. 异常概况：重大异常 {r['anomaly_overview']['major_count']} 条业务"]
    for s in r['anomaly_overview']['services']:
        lines.append(f"  {s['service_id']}: 基线 {s['baseline_availability_pct']}%，窗口均值 {s['analysis_mean_availability_pct']}%，"
                     f"平均下降 {s['mean_drop_pp']} 个百分点；最长连续 {s['longest_contiguous_minutes']} 分钟，"
                     f"首次 {s['first_decline_at']}，样本 {s['example_sample']['record_id'] if s['example_sample'] else '?'}")
    lines.append('2. 根因候选与原因（不是已证明的故障）')
    process = r.get('diagnostic_process', {})
    lines.append('  2.1 外部环境优先检查（环境代理异常不等于故障）')
    for obj in process.get('environment', {}).get('objects', []):
        lines.append(f"    {obj['object_id']}: {obj['assessment']}；代理升高 {obj['elevated_sample_count']} 个样本，"
                     f"首次 {obj['first_elevated_at']}；设备/业务共现首次 {obj['first_joint_observation_at']}")
        e = obj['peak_proxy_evidence']
        if e:
            lines.append(f"      {e['record_id']} {e['timestamp']} {e['field']}={e['value']}")
        if obj['elevated_sample_count']:
            lines.append('      '+obj['interpretation'])
    lines.append('  2.2 中继及相关链路容量核算（按同分钟到达量/有效容量）')
    candidate_ids = {c['object_id'] for c in r['root_cause_candidates']}
    for obj in process.get('capacity', {}).get('resources', []):
        if obj['object_type'] != 'node' and obj['object_id'] not in candidate_ids:
            continue
        lines.append(f"    {obj['object_id']}: {obj['assessment']}；有效样本 {obj['valid_samples']}/{obj['expected_samples']}，"
                     f"超限 {obj['overload_observed_minutes']} 分钟（累计，不一定连续）")
        sample = obj['representative_sample']
        if sample:
            lines.append(f"      {sample['timestamp']} 到达 {sample['ingress_mbps']} Mbps / 有效容量 {sample['effective_capacity_mbps']} Mbps；"
                         f"超出 {sample['excess_mbps']} Mbps；变化类型 {sample['change_driver']}")
            lines.append(f"      路由源需求汇总 {sample['routed_source_demand_mbps']} Mbps；与实测到达差额 "
                         f"{sample['source_demand_minus_ingress_mbps']} Mbps（源需求不等于逐跳到达）")
            for e in sample['evidence'][:2]:
                lines.append(f"      核算依据 {e['record_id']} {e['field']}={e['value']}")
    lines.append('  2.3 综合候选（保留支持与反对证据）')
    for c in r['root_cause_candidates']:
        lines.append(f"  {c['object_id']}：{c['hypothesis']}；关联 {len(c['affected_service_ids'])} 条，"
                     f"同资源正常 {len(c['unaffected_exposed_service_ids'])} 条")
        for e in c['supporting_evidence'][:3]:
            lines.append(f"    证据 {e['record_id']} {e['timestamp']} {e['field']}={e['value']} {e['unit']}")
        for e in c['counter_evidence'][:2]:
            lines.append(f"    反证 {e['record_id']} {e['timestamp']} {e['field']}={e['value']} {e['unit']}")
        for reason in c['missing_evidence'][:2]:
            lines.append('    待补 '+reason)
    lines.append('3. 潜在或轻微异常')
    for w in r['minor_anomalies']['watch']:
        s=w['service']
        lines.append(f"  关注 {w['service_id']}：峰值下降 {s['peak_drop_pp']} 个百分点，"
                     f"连续 {s['longest_contiguous_minutes']} 分钟；关联 {w['supporting_resource']}")
    for s in r['minor_anomalies']['observing']:
        lines.append(f"  观察中 {s['service_id']}：峰值下降 {s['peak_drop_pp']} 个百分点，"
                     f"最长 {s['longest_contiguous_minutes']} 分钟，证据未满足关注规则")
    lines.append('4. 影响与对照')
    lines.append('  重大异常业务：'+(', '.join(r['impact_and_controls']['affected_service_ids']) or '无'))
    for c in r['impact_and_controls']['candidate_controls'][:5]:
        lines.append(f"  {c['candidate_id']}：同资源正常 {c['same_resource_normal']}；"
                     f"同站不同路径正常 {c['same_destination_other_path_normal']}")
    for comp in process.get('path_controls', []):
        lines.append(f"  中继 {comp['relay_id']}：{comp['interpretation']}")
        pair = next((p for p in comp['comparisons'] if p['different_outgoing_path_normal_control']), None)
        if pair:
            lines.append('    同分钟对照 '+pair['timestamp'])
            for group in pair['groups']:
                declining = [s['service_id'] for s in group['services'] if s['state']=='declining']
                normal = [s['service_id'] for s in group['services'] if s['state']=='normal_sample']
                unknown = [s['service_id'] for s in group['services'] if s['state']=='unknown']
                lines.append(f"    {group['outgoing_link_id']}：下降 {declining}；正常采样 {normal}；未知 {unknown}")
    for s0 in r['anomaly_overview']['all_service_statuses']:
        if s0['classification']=='normal':
            lines.append(f"  正常业务 {s0['service_id']}：平均下降 {s0['mean_drop_pp']} 个百分点；"
                         f"峰值下降 {s0['peak_drop_pp']} 个百分点；"
                         f"样本 {s0['peak_sample']['record_id'] if s0['peak_sample'] else '?'}")
    s=r['conclusion_and_missing_evidence']
    lines.append('5. 结论与待补证据：'+s['assessment'])
    lines.append('  优先排查：'+str(s['priority_object']))
    lines.extend('  待补：'+e for e in s['next_evidence'])
    return '\n'.join(lines)


def main(argv=None) -> int:
    p=argparse.ArgumentParser(description='卫星服务时态本体诊断 (evaluation 数据严禁作为输入)')
    p.add_argument('--data',default=str(DEFAULT_DATA))
    sub=p.add_subparsers(dest='command',required=True)
    q=sub.add_parser('import-graph',help='用 Neo4j Driver 初始化图；只读取白名单')
    q=sub.add_parser('diagnose',help='生成终端报告与 JSON；默认必须连真实 MCP')
    q.add_argument('--case',help='CASE-001；缺省运行全部案例')
    q.add_argument('--cutoff',help='ISO-8601 截止时刻；缺省读取 cases.csv 初诊截止')
    q.add_argument('--graph-backend',choices=['mcp','local'],default='mcp',help='local 是显式测试模式，不可作为 MCP 验收')
    q.add_argument('--mcp-bin',default=os.environ.get('NEO4J_MCP_BIN','neo4j-mcp'))
    q.add_argument('--output',type=Path,default=Path('reports'))
    args=p.parse_args(argv)
    try:
        if args.command=='import-graph':
            uri=os.environ['NEO4J_MCP_URI']
            user=os.environ['NEO4J_MCP_USERNAME']
            password=os.environ['NEO4J_MCP_PASSWORD']
            database=os.environ.get('NEO4J_MCP_DATABASE','neo4j')
            print(json.dumps(import_graph(args.data,uri,user,password,database),ensure_ascii=False))
            return 0
        cases=[args.case] if args.case else [r['case_id'] for r in read_table(args.data,'cases')]
        if args.cutoff and len(cases)!=1:
            p.error('--cutoff 只能与 --case 同时使用')
        for case_id in cases:
            graph = LocalGraph(load_case(args.data,case_id,args.cutoff)['tables']) if args.graph_backend=='local' else MCPGraph(args.mcp_bin)
            report=analyze_case(args.data,case_id,args.cutoff,graph)
            args.output.mkdir(parents=True,exist_ok=True)
            target=args.output/(case_id+'.json')
            target.write_text(json.dumps(report,ensure_ascii=False,indent=2),encoding='utf-8')
            print(text_report(report))
            print('JSON：'+str(target.resolve()))
        return 0
    except (ValueError,RuntimeError,KeyError,OSError) as exc:
        print('诊断失败：'+str(exc),file=sys.stderr)
        return 2


if __name__=='__main__':
    raise SystemExit(main())
