import fs from 'node:fs/promises';
import path from 'node:path';
import crypto from 'node:crypto';
import assert from 'node:assert/strict';

// Synthetic engineering fixture, not an orbital/space-weather simulator.
const ROOT = path.resolve(import.meta.dirname, '..', '..');
const args = process.argv.slice(2);
if (args.includes('--help')) {
  console.log('node scripts/datasets/generate_satellite_demo.mjs [--out DIR] [--force]\nSynthetic development/evaluation fixtures only; never import this generator in diagnostic runtime.\nDefault output: data-output/satellite_demo_v1. Existing nonempty output is refused unless --force.');
  process.exit(0);
}
let outputArgument;
let force = false;
for (let i = 0; i < args.length; i++) {
  if (args[i] === '--out' && args[i + 1] && !args[i + 1].startsWith('--')) outputArgument = args[++i];
  else if (args[i] === '--force') force = true;
  else throw new Error(`Unknown or incomplete argument: ${args[i]}`);
}
const OUT = outputArgument ? path.resolve(outputArgument) : path.join(ROOT, 'data-output', 'satellite_demo_v1');
try {
  const existing = await fs.readdir(OUT);
  if (existing.length && !force) throw new Error(`Refusing to overwrite existing dataset: ${OUT}. Use a new --out directory, or explicitly pass --force.`);
} catch (error) {
  if (error.code !== 'ENOENT') throw error;
}
const SEED = 20260915;
const START = Date.parse('2026-09-15T09:30:00+08:00');
const MINUTES = 121;
const r = (v, digits = 4) => Math.round(v * 10 ** digits) / 10 ** digits;
const sid = n => `SAT-${String(n).padStart(2, '0')}`;
const gid = n => `GS-${String(n).padStart(2, '0')}`;
const iso = (minute, seconds = 0) => new Date(START + minute * 60000 + seconds * 1000)
  .toISOString().replace('Z', '+00:00');
const localTime = minute => new Date(START + minute * 60000 + 8 * 3600000)
  .toISOString().replace('Z', '+08:00');
const stable = (...keys) => {
  const h = crypto.createHash('sha256').update(`${SEED}:${keys.join(':')}`).digest();
  return h.readUInt32LE(0) / 4294967296;
};
const active = m => m >= 30 && m < 60;
const cases = Array.from({ length: 8 }, (_, i) => ({
  case_id: `CASE-${String(i + 1).padStart(3, '0')}`,
  dataset_kind: 'synthetic', time_zone: 'Asia/Shanghai',
  sample_start: localTime(0), sample_end_exclusive: localTime(MINUTES),
  sampling_seconds: 60, baseline_start: localTime(0), baseline_end_exclusive: localTime(30),
  analysis_start: localTime(30), analysis_end_exclusive: localTime(45),
  initial_diagnosis_cutoff: localTime(46),
  partition: i < 6 ? 'development' : 'holdout',
}));
const nodes = [];
for (let n = 1; n <= 42; n++) {
  nodes.push({ node_id: sid(n), node_type: 'satellite', constellation: `GROUP-${Math.ceil(n / 14)}`,
    forwarding_capacity_mbps: n === 20 ? 1000 : n === 21 ? 1600 : n === 24 ? 1300 : 500,
    nominal_bus_voltage_v: 28, valid_from: localTime(0), valid_to_exclusive: localTime(MINUTES),
    provenance: 'synthetic', });
}
for (let n = 1; n <= 3; n++) nodes.push({ node_id: gid(n), node_type: 'ground_station',
  constellation: '', forwarding_capacity_mbps: 2500, nominal_bus_voltage_v: 48,
  valid_from: localTime(0), valid_to_exclusive: localTime(MINUTES), provenance: 'synthetic' });
const nodeMap = new Map(nodes.map(n => [n.node_id, n]));
const links = [];
const linkId = (a, b) => `L-${a}-${b}`;
const relays = [sid(20), sid(21), sid(24)];
for (let n = 1; n <= 42; n++) {
  const src = sid(n);
  if (relays.includes(src)) continue;
  for (const relay of relays) links.push({ link_id: linkId(src, relay), source_node_id: src,
    target_node_id: relay, direction: 'directed', link_type: 'inter_satellite',
    nominal_capacity_mbps: 400, propagation_latency_ms: 8 + Math.abs(n - Number(relay.slice(-2))) * .22,
    visible_from: localTime(0), visible_to_exclusive: localTime(MINUTES),
    visibility_source: 'synthetic_contact_plan_not_ephemeris' });
}
for (const relay of relays) for (let g = 1; g <= 3; g++) links.push({
  link_id: linkId(relay, gid(g)), source_node_id: relay, target_node_id: gid(g),
  direction: 'directed', link_type: 'satellite_to_ground', nominal_capacity_mbps: 900,
  propagation_latency_ms: 18 + g * 2, visible_from: localTime(0),
  visible_to_exclusive: localTime(MINUTES), visibility_source: 'synthetic_contact_plan_not_ephemeris',
});
const linkMap = new Map(links.map(l => [l.link_id, l]));
const serviceSources = [3, 7, 10, 12, 16, 11, 18, 25, 27, 34, 1, 2, 4, 5, 6, 8, 9, 13];
const destinations = [1, 2, 1, 3, 2, 1, 2, 1, 3, 2, 1, 2, 1, 3, 1, 2, 2, 3];
const services = serviceSources.map((s, i) => ({ service_id: `SVC-${String(i + 1).padStart(3, '0')}`,
  source_satellite_id: sid(s), destination_ground_station_id: gid(destinations[i]),
  allowed_egress_ids: gid(destinations[i]), priority: 'standard',
  sla_latency_ms: 150, sla_availability_pct: 95, probe_attempts_per_minute: 10000,
  baseline_offered_mbps: i < 10 ? 55 : i < 14 ? 60 : 70,
}));
const serviceMap = new Map(services.map(s => [s.service_id, s]));
function routeAt(ci, si, minute, override) {
  const s = services[si];
  const relay = override?.get(s.service_id) ??
    (si < 10 ? (ci === 6 && si < 5 && minute >= 30 ? sid(21) : sid(20)) : si < 14 ? sid(21) : sid(24));
  return [s.source_satellite_id, relay, s.destination_ground_station_id];
}
const routes = [], routeHops = [];
for (let ci = 1; ci <= 8; ci++) for (let si = 0; si < services.length; si++) {
  const intervals = ci === 6 && si < 5 ? [[0, 30], [30, MINUTES]] : [[0, MINUTES]];
  for (let vi = 0; vi < intervals.length; vi++) {
    const [a, b] = intervals[vi];
    const ns = routeAt(ci, si, a);
    const route_id = `C${ci}-R${String(si + 1).padStart(3, '0')}-V${vi + 1}`;
    routes.push({ case_id: cases[ci - 1].case_id, route_id, service_id: services[si].service_id,
      effective_from: localTime(a), effective_to_exclusive: localTime(b),
      available_at: localTime(a === 30 ? 20 : 0), route_status: 'active',
      change_record_id: ci === 6 && si < 5 && vi === 1 ? 'EV-C6-PLAN' : '',
    });
    ns.forEach((n, j) => routeHops.push({ case_id: cases[ci - 1].case_id, route_id,
      hop_index: j, node_id: n, outgoing_link_id: j < ns.length - 1 ? linkId(n, ns[j + 1]) : '' }));
  }
}
function routeVersion(ci, si, m) {
  return `C${ci}-R${String(si + 1).padStart(3, '0')}-V${ci === 6 && si < 5 && m >= 30 ? 2 : 1}`;
}
function demandAt(ci, si, m) {
  let base = services[si].baseline_offered_mbps;
  if ((ci === 1 || ci === 8) && active(m) && si < 5) base = 160;
  if (ci === 1 && active(m) && si >= 14) base = 332;
  if (ci === 5 && m >= 30 && m < 75 && si >= 14) base = 295 + Math.min(1, (m - 30) / 10) * 37;
  // Tiny common cycle, no per-minute independent random jumps in the trend fixture.
  return r(base * (1 + .0015 * Math.sin(m / 7 + si)), 4);
}
function nodeProperties(ci, id, m) {
  const n = nodeMap.get(id);
  let survival = 1, radiation = 2 + Math.floor(stable(ci, id, m, 'rad') * 4), seu = 0, ecc = 0, resets = 0;
  let voltage = n.nominal_bus_voltage_v + (stable(ci, id, m, 'volt') - .5) * .15;
  if (ci === 2 && id === gid(1) && active(m)) { survival = .84; voltage = 39.5; }
  if ((ci === 4 || ci === 7) && active(m) && [sid(20), sid(24)].includes(id)) {
    radiation = 180 + Math.floor(stable(ci, id, m, 'event') * 60);
  }
  if (ci === 4 && id === sid(20) && active(m)) {
    survival = .88; seu = 7 + Math.floor(stable(ci, id, m, 'seu') * 6);
    ecc = 80 + Math.floor(stable(ci, id, m, 'ecc') * 40); resets = [30, 36, 42].includes(m) ? 1 : 0;
  }
  return { capacity: n.forwarding_capacity_mbps, survival, radiation, seu, ecc, resets, voltage };
}
function linkProperties(ci, id, m) {
  const l = linkMap.get(id);
  let capacity = l.nominal_capacity_mbps, survival = .99998, snr = 27 + stable(ci, id, m, 'snr') * 2;
  let ber = .0000001, state = 'UP';
  if (ci === 3 && id === linkId(sid(20), gid(1)) && active(m)) {
    capacity = 120; survival = .97; snr = 8.5; ber = .001;
  }
  if (ci === 8 && active(m) && [sid(21), sid(24)].includes(l.target_node_id)
    && serviceSources.slice(0, 10).map(sid).includes(l.source_node_id) && l.link_type === 'inter_satellite') {
    capacity = 0; survival = 0; state = 'DOWN'; snr = 0; ber = null;
  }
  return { capacity, survival, snr, ber, state };
}
// Every active path has source -> relay -> ground. Aggregate arrivals at each
// resource BEFORE proportional capacity sharing; downstream arrivals already
// exclude upstream losses. Thus real forwarding never exceeds capacity.
function simulate(ci, m, override) {
  const flows = services.map((s, si) => ({ s, si, offered: demandAt(ci, si, m),
    remaining: demandAt(ci, si, m), nodes: routeAt(ci, si, m, override), latency: 0 }));
  const nodeStats = new Map(), linkStats = new Map();
  for (let stage = 0; stage < 5; stage++) {
    const isNode = stage % 2 === 0, hop = Math.floor(stage / 2);
    const group = new Map();
    for (const f of flows) {
      const id = isNode ? f.nodes[hop] : linkId(f.nodes[hop], f.nodes[hop + 1]);
      if (!group.has(id)) group.set(id, []);
      group.get(id).push(f);
    }
    for (const [id, fsAt] of group) {
      const prop = isNode ? nodeProperties(ci, id, m) : linkProperties(ci, id, m);
      const requested = fsAt.reduce((a, f) => a + f.remaining, 0);
      const ratio = requested ? Math.min(1, prop.capacity / requested) : 1;
      const carried = requested * ratio * prop.survival;
      const util = prop.capacity ? requested / prop.capacity : requested ? Infinity : 0;
      const latency = (isNode ? 1.5 : linkMap.get(id).propagation_latency_ms) + Math.max(0, Math.min(util, 3) - .75) * 25;
      const stats = { requested, carried, discarded: requested - carried, ...prop, latency };
      (isNode ? nodeStats : linkStats).set(id, stats);
      for (const f of fsAt) { f.remaining *= ratio * prop.survival; f.latency += latency; }
    }
  }
  for (const f of flows) {
    // Device/service monitoring is independent from telemetry transport.
    const baseline = .994 + .001 * Math.sin(m / 11 + f.si) + .002 * stable(f.si, 'baseline');
    const handover = ci === 6 && f.si < 5 && m >= 30 && m < 32 ? .94 : 1;
    f.probeAttempts = f.s.probe_attempts_per_minute;
    f.probeSuccess = Math.round(f.probeAttempts * baseline * (f.remaining / f.offered) * handover);
    f.availability = f.probeSuccess / f.probeAttempts * 100;
    f.loss = (1 - f.remaining / f.offered) * 100;
  }
  return { flows, nodeStats, linkStats };
}
const traffic = [], nodeMetrics = [], linkMetrics = [], serviceMetrics = [], events = [];
function event(ci, suffix, objectType, objectId, kind, code, severity, a, b, details, knownAt = a, value = '', unit = '') {
  const id = `EV-C${ci}-${suffix}`;
  const futureEnd = b !== null && b > knownAt;
  events.push({ event_id: id, related_event_id: '', case_id: cases[ci - 1].case_id,
    object_type: objectType, object_id: objectId, event_kind: kind, event_code: code, severity,
    event_start: localTime(a), event_end_exclusive: b === null || futureEnd ? '' : localTime(b),
    planned_end: kind === 'planned_change' && b !== null ? localTime(b) : '',
    event_status: futureEnd ? 'open' : 'recorded',
    available_at: localTime(knownAt), observed_value: value, unit, details });
  if (futureEnd) events.push({ event_id: `${id}-CLOSE`, related_event_id: id,
    case_id: cases[ci - 1].case_id, object_type: objectType, object_id: objectId,
    event_kind: 'state_update', event_code: code, severity: 'info',
    event_start: localTime(a), event_end_exclusive: localTime(b), planned_end: '', event_status: 'closed',
    available_at: localTime(b), observed_value: '', unit: '', details: '记录该事件结束；仅此时起可获知实际结束时间' });
}
event(1, 'A1', 'satellite', sid(20), 'alarm', 'FORWARDING_QUEUE_HIGH', 'warning', 30, 60, '转发队列超过演示阈值', 31);
event(1, 'A2', 'satellite', sid(24), 'alarm', 'FORWARDING_LOAD_HIGH', 'warning', 32, 60, '转发负载持续偏高', 33);
event(1, 'CH', 'service', 'SVC-001', 'change', 'TRAFFIC_POLICY_RESTORED', 'info', 60, 60, '业务流量策略恢复', 60);
event(2, 'A1', 'ground_station', gid(1), 'alarm', 'POWER_BUS_LOW', 'critical', 30, 60, '接收设备供电电压偏低', 31, 39.5, 'V');
event(2, 'CH', 'ground_station', gid(1), 'change', 'POWER_MODULE_SERVICE', 'info', 60, 60, '供电模块维护完成', 60);
event(3, 'A1', 'link', linkId(sid(20), gid(1)), 'alarm', 'LOW_SNR', 'critical', 30, 60, '信噪比下降、误码计数升高', 31, 8.5, 'dB');
event(3, 'CH', 'link', linkId(sid(20), gid(1)), 'change', 'LINK_REACQUIRED', 'info', 60, 60, '链路重新捕获并恢复', 60);
for (const ci of [4, 7]) for (const n of [sid(20), sid(24)]) {
  event(ci, `RAD-${n}`, 'satellite', n, 'alarm', 'ENV_COUNTER_HIGH', 'warning', 30, 60, '环境监测计数升高，单独不能证明设备受损', 31, 200, 'synthetic_counts/min');
}
event(4, 'SEU', 'satellite', sid(20), 'alarm', 'MEMORY_ERROR_COUNT_HIGH', 'critical', 30, 60, '存储错误计数升高', 31);
for (const m of [30, 36, 42]) event(4, `RESET-${m}`, 'satellite', sid(20), 'event', 'PROCESSOR_RESET', 'critical', m, m + 1, '处理器重启事件', m + 1);
event(4, 'CH', 'satellite', sid(20), 'change', 'REDUNDANT_COMPUTER_ENABLED', 'info', 60, 60, '切换备用计算单元', 60);
event(5, 'A1', 'satellite', sid(24), 'alarm', 'FORWARDING_LOAD_HIGH', 'warning', 37, 75, '负载持续接近或超过容量', 38);
event(5, 'CH', 'satellite', sid(24), 'change', 'TRAFFIC_SHAPING_UPDATED', 'info', 75, 75, '调整流量整形配置', 75);
event(6, 'PLAN', 'satellite', sid(20), 'planned_change', 'PLANNED_HANDOVER', 'info', 30, 32, 'SVC-001至SVC-005切换至SAT-21；计划内过渡最长120秒', 20);
event(6, 'DONE', 'satellite', sid(21), 'change', 'HANDOVER_COMPLETED', 'info', 32, 32, '计划切换完成', 32);
event(8, 'GAP', 'satellite', sid(20), 'data_quality', 'TELEMETRY_STREAM_MISSING', 'warning', 30, 60, '节点及关联链路遥测中断，缺失不等于设备故障', 32);
for (const relay of [sid(21), sid(24)]) event(8, `CONTACT-${relay}`, 'satellite', relay,
  'event', 'CONTACTS_UNAVAILABLE', 'warning', 30, 60, '当前接触计划中的源星至该中继链路不可用', 30);

for (let ci = 1; ci <= 8; ci++) {
  const caseId = cases[ci - 1].case_id;
  for (let m = 0; m < MINUTES; m++) {
    const sim = simulate(ci, m);
    for (const f of sim.flows) {
      const gap = ci === 8 && active(m) && f.si < 10;
      traffic.push({ case_id: caseId, timestamp: localTime(m), available_at: localTime(m + 65 / 60),
        service_id: f.s.service_id, route_id: routeVersion(ci, f.si, m),
        offered_mbps: gap ? null : f.offered, measurement_status: gap ? 'missing' : 'observed' });
      serviceMetrics.push({ sample_id: `${caseId}-S${f.si + 1}-T${m}`, case_id: caseId,
        timestamp: localTime(m), available_at: localTime(m + 65 / 60), service_id: f.s.service_id,
        source_satellite_id: f.s.source_satellite_id, route_id: routeVersion(ci, f.si, m),
        probe_attempts: f.probeAttempts, probe_successes: f.probeSuccess, availability_pct: r(f.availability),
        delivered_mbps: gap ? null : r(f.remaining), packet_loss_pct: gap ? null : r(f.loss), mean_latency_ms: r(f.latency, 3),
        throughput_measurement_status: gap ? 'missing' : 'observed',
        measurement_status: 'observed' });
    }
    for (const n of nodes) {
      const p = nodeProperties(ci, n.node_id, m);
      const s = sim.nodeStats.get(n.node_id) ?? { requested: 0, carried: 0, discarded: 0, latency: 1.5 };
      const gap = ci === 8 && active(m) && [sid(20), ...serviceSources.slice(0, 10).map(sid)].includes(n.node_id);
      const demandUtil = s.requested / p.capacity;
      nodeMetrics.push({ sample_id: `${caseId}-${n.node_id}-T${m}`, case_id: caseId, timestamp: localTime(m),
        available_at: localTime(m + 65 / 60), node_id: n.node_id, node_type: n.node_type,
        effective_capacity_mbps: gap ? null : p.capacity, ingress_mbps: gap ? null : r(s.requested),
        forwarded_mbps: gap ? null : r(s.carried), discarded_mbps: gap ? null : r(s.discarded),
        demand_utilization_pct: gap ? null : r(demandUtil * 100),
        forwarding_utilization_pct: gap ? null : r(s.carried / p.capacity * 100),
        queue_depth_mb: gap ? null : r(Math.min(256, Math.max(0, s.requested - p.capacity) * 60 / 8 * .1)),
        cpu_utilization_pct: gap ? null : r(Math.min(99, 12 + Math.min(demandUtil, 1.2) * 70), 2),
        temperature_c: gap ? null : r(35 + Math.min(demandUtil, 1.2) * 18, 2),
        bus_voltage_v: gap ? null : r(p.voltage, 3), radiation_proxy_counts_per_min: gap ? null : p.radiation,
        seu_events_per_min: gap ? null : p.seu, ecc_corrected_events_per_min: gap ? null : p.ecc,
        reset_events_per_min: gap ? null : p.resets, measurement_status: gap ? 'missing' : 'observed' });
    }
    for (const l of links) {
      const p = linkProperties(ci, l.link_id, m);
      const s = sim.linkStats.get(l.link_id) ?? { requested: 0, carried: 0, discarded: 0, latency: l.propagation_latency_ms };
      const gap = ci === 8 && active(m) && [l.source_node_id, l.target_node_id].includes(sid(20));
      linkMetrics.push({ sample_id: `${caseId}-${l.link_id}-T${m}`, case_id: caseId,
        timestamp: localTime(m), available_at: localTime(m + 65 / 60), link_id: l.link_id,
        operational_state: p.state, effective_capacity_mbps: gap ? null : p.capacity,
        ingress_mbps: gap ? null : r(s.requested), transmitted_mbps: gap ? null : r(s.carried),
        discarded_mbps: gap ? null : r(s.discarded),
        demand_utilization_pct: gap || !p.capacity ? null : r(s.requested / p.capacity * 100),
        forwarding_utilization_pct: gap || !p.capacity ? null : r(s.carried / p.capacity * 100),
        snr_db: gap ? null : r(p.snr, 3), bit_error_rate: gap ? null : p.ber,
        mean_latency_ms: gap ? null : r(s.latency, 3), measurement_status: gap ? 'missing' : 'observed' });
    }
  }
  console.log(`Generated ${caseId}`);
}

const rules = {
  schema_version: '1.0', provenance: 'demonstration_assumptions_not_industry_standard',
  availability: { object: 'end_to_end_service_from_source_satellite_to_fixed_ground_station',
    formula: '100 * probe_successes / probe_attempts', unit: 'percent_0_100',
    baseline: 'per_service_mean_over_case_baseline_window',
    drop_unit: 'percentage_points_not_relative_percent',
    major_alert: { drop_pp_strictly_greater_than: 5, consecutive_valid_samples: 3 },
    watch: { drop_pp_at_least: 1, drop_pp_at_most: 5, consecutive_valid_samples: 10,
      supporting_signal: 'route_resource_demand_utilization_ge_85_pct_or_equipment_error_event',
      meaning: 'subthreshold_observed_degradation_not_future_fault_probability' },
    planned_change: 'retain_observations_but_classify_separately_with_published_time_and_allowed_duration',
    missing: 'null_is_not_zero_and_breaks_consecutive_evidence',
  },
  diagnostics: { initial_cutoff_field: 'initial_diagnosis_cutoff',
    evidence_filter: 'available_at <= cutoff; complete samples must end <= cutoff',
    recovery_evidence: 'post_event_review_only_if_after_initial_cutoff',
    causal_label_policy: 'candidate_or_supported_hypothesis_until_independent_confirmation',
    confidence: 'no_numeric_fault_probability_without_calibration' },
  routing: { direction: 'directed', preserve_source_and_allowed_egress: true,
    max_post_reroute_demand_utilization_pct: 85, max_latency_ms: 150,
    require_operational_up_and_contact_window: true, evaluate_all_rerouted_flows_together: true,
    reservation: 'keep_15_pct_node_and_link_capacity_headroom',
    improvement: 'synthetic_model_estimate_not_observed_post_switch_measurement',
    action: 'recommendation_only_no_real_network_control' },
};
const truth = {
  evaluation_only: true, warning: 'Never load this directory into the diagnosis context, prompt, candidate generation, or training features.',
  cases: [
    [1, 'relay_capacity_overload', sid(20), 'satellite', 30, 60, '十条共用中继的业务受影响；另有四条经SAT-24的轻微下降', 'major_anomaly'],
    [2, 'ground_station_power_degradation', gid(1), 'ground_station', 30, 60, '同站不同中继的业务下降；其他站对照正常', 'major_anomaly'],
    [3, 'single_link_capacity_and_error_degradation', linkId(sid(20), gid(1)), 'link', 30, 60, '仅经过该链路的业务明显下降', 'major_anomaly'],
    [4, 'injected_radiation_related_computer_upset', sid(20), 'satellite', 30, 60, '环境计数、存储错误、重启共同出现；SAT-24环境计数高但业务正常', 'major_anomaly'],
    [5, 'gradual_subthreshold_load_degradation', sid(24), 'satellite', 30, 75, '四条业务缓慢下降，始终不超过5个百分点', 'watch'],
    [6, 'planned_handover_transient', sid(20), 'satellite', 30, 32, '两点瞬时下降后恢复，不满足连续三点重大异常规则', 'planned_change'],
    [7, 'environment_counter_without_service_fault', '', '', 30, 60, '环境计数升高但没有设备错误或明显业务下降', 'normal_service'],
    [8, 'relay_overload_with_missing_telemetry_and_blocked_alternatives', sid(20), 'satellite', 30, 60, '注入真因仍是过载，但实时证据不完整，应保留不确定性且不强行推荐改路', 'insufficient_cause_evidence'],
  ].map(([ci, cause, id, type, a, b, notes, expected]) => ({ case_id: cases[ci - 1].case_id,
    planted_cause: cause, planted_object_id: id, planted_object_type: type,
    event_start: localTime(a), event_end_exclusive: localTime(b), expected_handling: expected, notes,
    truth_basis: 'generator_injection_not_real_world_confirmed_incident' })),
};

const byCaseService = new Map();
for (const row of serviceMetrics) {
  const key = `${row.case_id}/${row.service_id}`;
  if (!byCaseService.has(key)) byCaseService.set(key, []);
  byCaseService.get(key).push(row);
}
const avg = xs => xs.reduce((a, b) => a + b, 0) / xs.length;
const overview = [];
function longest(xs, predicate) { let count = 0, max = 0; for (const x of xs) { count = predicate(x) ? count + 1 : 0; max = Math.max(max, count); } return max; }
for (const ca of cases) for (const s of services) {
  const rows = byCaseService.get(`${ca.case_id}/${s.service_id}`);
  const baseline = avg(rows.slice(0, 30).map(x => x.availability_pct));
  const observed = rows.slice(30, 45), all = rows.slice(30, 75);
  overview.push({ case_id: ca.case_id, service_id: s.service_id, source_satellite_id: s.source_satellite_id,
    baseline_availability_pct: r(baseline), analysis_mean_availability_pct: r(avg(observed.map(x => x.availability_pct))),
    mean_drop_pp: r(baseline - avg(observed.map(x => x.availability_pct))),
    initial_major_alert: longest(observed, x => baseline - x.availability_pct > 5) >= 3,
    initial_watch: longest(observed, x => baseline - x.availability_pct >= 1 && baseline - x.availability_pct <= 5) >= 10,
    longest_major_run_in_full_event: longest(all, x => baseline - x.availability_pct > 5),
    longest_watch_run_in_full_event: longest(all, x => baseline - x.availability_pct >= 1 && baseline - x.availability_pct <= 5),
  });
}

// A reference reroute experiment for evaluation, not an application diagnosis.
// Move all TEN affected flows together, keeping service endpoints unchanged.
const override = new Map(services.slice(0, 10).map(s => [s.service_id, sid(21)]));
const before = simulate(1, 40), after = simulate(1, 40, override);
const rerouteReference = {
  evaluation_only: true, case_id: 'CASE-001', timestamp: localTime(40),
  experiment_kind: 'same_demand_synthetic_model_counterfactual_not_a_real_switch',
  simultaneous_service_count: override.size,
  changes: services.slice(0, 10).map((s, i) => ({ service_id: s.service_id,
    before_nodes: before.flows[i].nodes, after_nodes: after.flows[i].nodes,
    before_availability_pct: r(before.flows[i].availability), estimated_after_availability_pct: r(after.flows[i].availability),
    estimated_after_latency_ms: r(after.flows[i].latency, 3) })),
  all_services_comparison: services.map((s, i) => ({ service_id: s.service_id,
    moved: override.has(s.service_id), before_availability_pct: r(before.flows[i].availability),
    estimated_after_availability_pct: r(after.flows[i].availability),
    estimated_after_latency_ms: r(after.flows[i].latency, 3),
    meets_availability_sla: after.flows[i].availability >= s.sla_availability_pct,
    meets_latency_sla: after.flows[i].latency <= s.sla_latency_ms,
    not_degraded_by_reroute: after.flows[i].availability >= before.flows[i].availability - .01,
  })),
  all_used_resource_peak_demand_utilization_pct: r(Math.max(
    ...[...after.nodeStats.values(), ...after.linkStats.values()].map(x => x.requested / x.capacity * 100))),
  selected_relay_demand_utilization_pct: r(after.nodeStats.get(sid(21)).requested / 1600 * 100),
  feasible_for_changed_services_with_15pct_headroom: [...after.nodeStats, ...after.linkStats]
    .filter(([id]) => id !== sid(24) && !id.includes(sid(24)))
    .every(([, x]) => x.requested <= x.capacity * .85 + .0001),
  preexisting_unmoved_risk: 'SAT-24 and its four services remain degraded; this proposal only resolves the SAT-20 group.',
};

// Generator quality checks are independent from any future diagnosis algorithm.
const checks = [];
function check(name, fn) { fn(); checks.push({ check: name, result: 'passed' }); }
check('unique primary keys', () => {
  for (const [rows, field] of [[nodes, 'node_id'], [links, 'link_id'], [services, 'service_id'], [routes, 'route_id'], [events, 'event_id'], [nodeMetrics, 'sample_id'], [linkMetrics, 'sample_id'], [serviceMetrics, 'sample_id']])
    assert.equal(new Set(rows.map(x => x[field])).size, rows.length, field);
});
check('route continuity endpoints and validity', () => {
  for (const route of routes) {
    assert(serviceMap.has(route.service_id));
    const hs = routeHops.filter(x => x.route_id === route.route_id).sort((a, b) => a.hop_index - b.hop_index);
    assert.equal(hs.length, 3);
    assert.equal(hs[0].node_id, serviceMap.get(route.service_id).source_satellite_id);
    assert(serviceMap.get(route.service_id).allowed_egress_ids.split(';').includes(hs.at(-1).node_id));
    hs.forEach((h, i) => { assert(nodeMap.has(h.node_id)); assert.equal(h.hop_index, i);
      if (i < 2) { const l = linkMap.get(h.outgoing_link_id); assert(l); assert.equal(l.source_node_id, h.node_id);
        assert.equal(l.target_node_id, hs[i + 1].node_id); assert(Date.parse(l.visible_from) <= Date.parse(route.effective_from));
        assert(Date.parse(l.visible_to_exclusive) >= Date.parse(route.effective_to_exclusive)); }
    });
  }
});
check('capacity and rate conservation for observed telemetry', () => {
  for (const x of [...nodeMetrics, ...linkMetrics]) {
    if (x.measurement_status !== 'observed') continue;
    const sent = x.forwarded_mbps ?? x.transmitted_mbps;
    assert(sent <= x.effective_capacity_mbps + .0002);
    assert(Math.abs(x.ingress_mbps - sent - x.discarded_mbps) < .0003);
    assert(x.ingress_mbps >= 0 && sent >= 0);
  }
});
check('service numerator denominator bounds and timestamp availability', () => {
  for (const x of serviceMetrics) {
    assert.equal(x.availability_pct, r(x.probe_successes / x.probe_attempts * 100));
    assert(x.probe_successes >= 0 && x.probe_successes <= x.probe_attempts);
    assert(Date.parse(x.available_at) >= Date.parse(x.timestamp) + 60000);
  }
});
check('known synthetic case characteristics', () => {
  const get = (ci, a, b) => overview.filter(x => x.case_id === cases[ci - 1].case_id).slice(a, b);
  assert(get(1, 0, 10).every(x => x.initial_major_alert));
  assert(get(1, 10, 14).every(x => !x.initial_major_alert && !x.initial_watch));
  assert(get(1, 14, 18).every(x => x.initial_watch && !x.initial_major_alert));
  assert(get(5, 14, 18).every(x => x.longest_watch_run_in_full_event >= 10 && x.longest_major_run_in_full_event === 0));
  assert(get(6, 0, 18).every(x => !x.initial_major_alert));
  assert(get(7, 0, 18).every(x => !x.initial_major_alert && !x.initial_watch));
  assert(get(8, 10, 18).every(x => !x.initial_major_alert && !x.initial_watch));
  assert(get(2, 0, 18).filter(x => x.initial_major_alert).every(x => serviceMap.get(x.service_id).destination_ground_station_id === gid(1)));
  assert(get(3, 10, 18).every(x => !x.initial_major_alert));
});
check('missing telemetry remains null not zero', () => {
  const missing = nodeMetrics.filter(x => x.measurement_status === 'missing'); assert.equal(missing.length, 330);
  assert(missing.every(x => x.ingress_mbps === null && x.forwarded_mbps === null));
  assert(traffic.some(x => x.measurement_status === 'missing' && x.offered_mbps === null));
  const missingTransport = serviceMetrics.filter(x => x.throughput_measurement_status === 'missing');
  assert.equal(missingTransport.length, 300);
  assert(missingTransport.every(x => x.delivered_mbps === null && x.packet_loss_pct === null && x.probe_attempts > 0));
});
check('event state updates do not leak future recovery', () => {
  for (const e of events) if (e.event_end_exclusive) assert(Date.parse(e.event_end_exclusive) <= Date.parse(e.available_at));
  assert(events.some(e => e.event_status === 'open' && !e.event_end_exclusive));
});
check('group rerouting conserves endpoint and respects changed resource headroom', () => {
  assert.equal(rerouteReference.simultaneous_service_count, 10);
  assert(rerouteReference.feasible_for_changed_services_with_15pct_headroom);
  assert(rerouteReference.changes.every(x => x.after_nodes[1] === sid(21) && x.estimated_after_availability_pct > x.before_availability_pct + 5 && x.estimated_after_latency_ms < 150));
  assert(rerouteReference.all_services_comparison.every(x => x.meets_availability_sla && x.meets_latency_sla && x.not_degraded_by_reroute));
  for (const f of after.flows) assert.equal(f.nodes.at(-1), f.s.destination_ground_station_id);
});
check('no feasible alternative and ground endpoint constraint represented', () => {
  for (const s of services.slice(0, 10)) for (const relay of [sid(21), sid(24)])
    assert.equal(linkProperties(8, linkId(s.source_satellite_id, relay), 40).state, 'DOWN');
  assert(services.filter(s => s.destination_ground_station_id === gid(1)).every(s => s.allowed_egress_ids === gid(1)));
});

const tables = { cases, nodes, links, services, routes, route_hops: routeHops, traffic,
  node_metrics: nodeMetrics, link_metrics: linkMetrics, service_metrics: serviceMetrics, events };
const descriptions = {
  cases: '案例时间范围和分析截止时刻；编号不包含故障类型', nodes: '卫星与地面站资产，额定转发容量',
  links: '有向通信链路、额定带宽、传播时延及模拟可见窗口', services: '源星至固定地面站的端到端服务，含SLA和探测口径',
  routes: '分案例、分服务、带生效时间的路由版本', route_hops: '路由每一跳的节点和下一条有向链路',
  traffic: '每分钟业务请求流量；缺失为留空', node_metrics: '节点转发负载、队列、电压、环境计数和设备错误',
  link_metrics: '链路状态、带宽、负载、SNR、误码率', service_metrics: '端到端服务探测、可用度、丢包、交付流量、时延',
  events: '告警、计划切换、维护和数据质量记录；含证据可获得时间',
};
const fieldNotes = {
  timestamp: '采样区间开始时间；每条样本覆盖其后60秒', available_at: '证据可获得时间；初始诊断必须按此过滤，不能提前读取',
  sample_end_exclusive: '末端不包含；包含121个一分钟采样点',
  availability_pct: '0至100；100×成功探测数/有效探测总数，属于网络服务可用度，不是诊断置信度',
  demand_utilization_pct: '到达请求流量/有效容量×100，可超过100，表示超额请求',
  forwarding_utilization_pct: '实际转发或发送流量/有效容量×100，不超过100',
  ingress_mbps: '资源在该采样区间收到的流量，已扣除上游丢弃，不是所有源请求量重复相加',
  discarded_mbps: '该资源收到但未转发/发送的流量；包含容量不足或设备/链路错误造成的模拟损失',
  effective_capacity_mbps: '当前有效容量；缺失留空，链路DOWN时为0',
  offered_mbps: '源端请求流量；Mbps；并非保证已转发的流量',
  delivered_mbps: '最终抵达目标地面站的业务流量；Mbps',
  packet_loss_pct: '100×(1-交付流量/源端请求流量)，不等同于业务探测失败率',
  mean_latency_ms: '简化传播、处理及负载排队模型的平均值；不是轨道物理仿真结果',
  probe_attempts: '每分钟10000次抽象服务探测，不代表10000台设备，也不是接口包计数',
  probe_successes: '成功完成的服务探测次数，包含固定基线误差和路径传输影响',
  radiation_proxy_counts_per_min: '虚构环境计数器的每分钟计数；不是实测辐射通量、剂量或行业危险阈值',
  seu_events_per_min: '模拟单粒子翻转类设备事件计数；用于联合证据，不单独证明现实故障原因',
  ecc_corrected_events_per_min: '每分钟已纠正存储错误事件，不是累计计数',
  reset_events_per_min: '每分钟重启事件数量',
  bit_error_rate: '模拟比特误码比例；SNR与BER是场景辅助观测，不使用真实调制解调信道模型换算',
  snr_db: '模拟接收信噪比，单位dB；DOWN时0只是本数据约定，不表示物理测量',
  measurement_status: 'observed或missing；null/空字段表示缺失，不能填0或自动认定正常',
  throughput_measurement_status: '交付流量及派生丢包率是否有观测；与独立服务探测的measurement_status分开',
  operational_state: 'UP或DOWN；与遥测是否缺失分开',
  queue_depth_mb: '采样内的简化瞬时积压代理值，非精确跨分钟队列积分',
  allowed_egress_ids: '允许的业务出口地面站，以分号分隔；本版每条服务固定一个出口，不能擅自换站',
  initial_diagnosis_cutoff: '初次报告能看到的最晚证据时间；之后维护和恢复仅供复盘',
  event_end_exclusive: '事件结束时间；用于区间判断，不是该结束信息已提前获知的时间，初诊只可读取available_at前已知内容',
  planned_end: '提前发布的计划结束时间，不等于实际恢复时间',
  related_event_id: '状态更新所对应的原始事件ID；需按available_at选取当时最新状态',
};
function csvEncode(value) {
  if (value === null || value === undefined) return '';
  const s = String(value); return /[",\r\n]/.test(s) ? `"${s.replaceAll('"', '""')}"` : s;
}
await fs.mkdir(path.join(OUT, 'observed'), { recursive: true });
await fs.mkdir(path.join(OUT, 'evaluation'), { recursive: true });
const catalog = [];
for (const [name, rows] of Object.entries(tables)) {
  const columns = Object.keys(rows[0]);
  const text = '\uFEFF' + [columns.join(','), ...rows.map(row => columns.map(c => csvEncode(row[c])).join(','))].join('\r\n') + '\r\n';
  const relative = `observed/${name}.csv`;
  await fs.writeFile(path.join(OUT, relative), text, 'utf8');
  catalog.push({ file: relative, rows: rows.length, columns: columns.length, description: descriptions[name],
    sha256: crypto.createHash('sha256').update(text).digest('hex'),
    fields: columns.map(c => ({ name: c, type: rows.some(row => typeof row[c] === 'number') ? 'number_or_null' : 'string',
      description: fieldNotes[c] ?? (c.endsWith('_id') ? '关联标识；必须按case_id和具体标识联接' : c.endsWith('_mbps') ? 'Mbps' : c.endsWith('_pct') ? '百分数0至100（请求利用率可大于100）' : c) })) });
}
const writeJSON = (name, object) => fs.writeFile(path.join(OUT, name), JSON.stringify(object, null, 2) + '\n', 'utf8');
await writeJSON('demo_rules.json', rules);
await writeJSON('data_dictionary.json', { schema_version: '1.0', encoding: 'UTF-8 with BOM for CSV', delimiter: ',',
  null_representation: 'empty CSV field', join_scope: 'time-varying tables require case_id; never mix timelines from independent cases', tables: catalog });
await writeJSON('evaluation/ground_truth.json', truth);
await writeJSON('evaluation/reroute_reference.json', rerouteReference);
await writeJSON('evaluation/derived_service_checks.json', overview);
await writeJSON('validation_report.json', { status: 'passed', checks, totals: Object.fromEntries(catalog.map(c => [c.file, c.rows])),
  total_csv_data_rows: catalog.reduce((a, c) => a + c.rows, 0),
  scope: 'data consistency and planted scenario checks, not diagnostic model accuracy',
});
await writeJSON('manifest.json', { dataset_id: 'satellite_demo_v1', schema_version: '1.0', dataset_kind: 'synthetic',
  generator_seed: SEED, independent_cases: cases.length, satellites: 42, ground_stations: 3,
  directed_links: links.length, services_per_case: services.length, samples_per_case: MINUTES,
  observation_csv_files: catalog.map(({ file, rows, sha256 }) => ({ file, rows, sha256 })),
  diagnosis_allowlist: [...catalog.map(c => c.file), 'demo_rules.json', 'data_dictionary.json'],
  evaluation_excluded_from_diagnosis: 'evaluation/',
  observation_limitations: ['not real telemetry', 'no real ephemeris or contact prediction', 'no calibrated space radiation physics',
    'sampling is one minute; not suitable for subsecond faults', '8 independent designed cases cannot establish real-world accuracy'],
});
const dictionaryMD = `# 卫星网络模拟数据字段说明\n\n所有 CSV 为 UTF-8 BOM，第一行为英文字段名。时间带时区；空字段为缺失，禁止按0处理。\n\n` +
  catalog.map(c => `## ${c.file}\n\n${c.description}。共 ${c.rows} 行。\n\n| 字段 | 含义 |\n| --- | --- |\n` +
    c.fields.map(f => `| ${f.name} | ${f.description} |`).join('\n')).join('\n\n');
await fs.writeFile(path.join(OUT, '字段说明.md'), dictionaryMD + '\n', 'utf8');
const caseGuide = truth.cases.map(c => `| ${c.case_id} | ${c.planted_object_id || '无故障对象'} | ${c.notes} |`).join('\n');
await fs.writeFile(path.join(OUT, 'evaluation', '案例答案说明.md'), `# 模拟案例答案（只用于验收）\n\n不要将本目录作为诊断模型输入。\n\n| 案例 | 注入对象 | 预设场景与检查点 |\n| --- | --- | --- |\n${caseGuide}\n\nCASE-001 的参考改路将10条业务同时从SAT-20迁至SAT-21；原有SAT-24轻微下降仍需另行处理。CASE-002 固定业务出口为GS-01时，仅换中继不能解决站侧供电异常。CASE-008 的备用链路不可用，应输出无满足约束的备选路径。\n\n这些是生成器设置的答案，不是我们系统已经识别正确的结果。\n`, 'utf8');
await fs.writeFile(path.join(OUT, 'README.md'), `# 卫星网络分析模拟数据集 v1\n\n## 这份数据用来做什么\n\n用于开发图中“异常概况、共同依赖、反向检查、分析报告”，并扩展异常原因、轻微持续下降和备选通信路径。全部为自行生成的模拟数据，不是甲方实测或截图数据抄录。\n\n- 42颗卫星、3个地面站、${links.length}条有向链路。\n- 8个独立案例，每个案例18条端到端业务。\n- 时间：2026-09-15 09:30至11:30，每分钟一个样本，共121点。\n- 基线09:30至10:00；首轮分析10:00至10:15；初诊证据截止10:16。末端时间均不包含。\n- 11个CSV文件，共${catalog.reduce((a, c) => a + c.rows, 0).toLocaleString('en-US')}行数据。\n\n## 先看哪几个文件\n\n| 文件 | 用途 |\n| --- | --- |\n${catalog.map(c => `| ${c.file} | ${c.description}（${c.rows}行） |`).join('\n')}\n| demo_rules.json | 演示异常阈值、时间规则、改路约束 |\n| 字段说明.md / data_dictionary.json | 中文字段解释、单位、联接和缺失约定 |\n| evaluation/ | 模拟故障答案与改路参考，仅用于验收 |\n| validation_report.json | 生成器的数据一致性检查结果，不是系统诊断准确率 |\n\n## 指标口径\n\n“可用度”指从源卫星到固定目标地面站的端到端服务成功率，等于成功探测数/总探测数×100，不表示卫星硬件健康度，也不是AI判断的可信度。99%降到92%是下降7个百分点。\n\n演示重大异常：相对该业务正常基线下降严格大于5个百分点，连续3个有效采样点。关注对象：下降1至5个百分点且持续10点，并伴随高负载或设备错误。规则可配置，不是行业标准；持续关注也不等于必然发生故障。计划切换单独标记，不能删除原始异常记录。\n\n## 如何防止“看答案做分析”\n\n诊断只能读取manifest.json中的diagnosis_allowlist。案例编号和输入表不写预设根因。evaluation目录、生成器内部配置不得被检索进提示词或诊断上下文。初诊按available_at过滤；故障后的维护、恢复不能用于事先判断。事件结束信息应由状态更新发布，不能让首个告警提前知道未来恢复时间。\n\n## 数据生成模型与限制\n\n固定种子${SEED}，所有案例可重现。业务流量依次经过源节点、源星到中继链路、中继节点、中继到地面站链路和地面站。每个资源先汇总真实到达的流量，再按容量等比例分配，扣除模拟设备/传输损失；下游只收到上游实际转发量。请求利用率可大于100%，实际转发不超过容量。节点负载按Mbps计算，不用“路由条数多”替代容量判断。\n\n探测可用度由路径交付比例、正常探测基线和计划切换过渡共同产生；丢包率与服务探测失败率不是同一指标。队列、温度、CPU与SNR是可解释的简化代理模型，未进行真实轨道、无线调制、跨分钟队列或空间环境物理仿真。未承载这18条业务的节点流量为0，不能据此推断现实全网没有其他业务。\n\n辐射相关场景分别提供虚构环境计数、存储错误和重启；另有环境计数高但业务正常的对照。NASA说明空间辐射可能造成电子器件单粒子效应，但本数据的计数、阈值和事件关系均为演示设定，不可套用到真实卫星：[NASA空间辐射与航天器电子器件介绍](https://science.nasa.gov/science-research/heliophysics/how-nasa-prepares-spacecraft-for-the-harsh-radiation-of-space/)。\n\n## 备选路径怎么用\n\n先按当时可用的有向链路生成候选路径，保持源和允许的地面站出口不变，再同时放入全部待迁移业务，检查节点、链路利用率不超过85%及业务时延不超过150ms。不能只单独检查每条路径。链路可见窗口是模拟接触计划，非星历计算。\n\n参考试验保存在evaluation/reroute_reference.json：它是同一需求下的模拟前后对照，不是实际切换测量，也不是已经上线的路由优化算法。没有满足约束的路径时必须明确报告“暂无可行路径”。\n\n## 接入现有系统的下一步\n\n1. 先保存当前系统版本，再增加卫星数据文件适配器，按case_id和时间读取这些表。\n2. 建模Satellite、GroundStation、CommunicationLink、Route、NetworkService、MetricObservation和AlarmEvent等对象，并导入带时间的路由关系。\n3. 增加读取校验、异常/关注检测、共同依赖、证据比较、备选路径校验和报告生成处理器。\n4. 通过现有task_plan、task_key、执行记录和报告下载串起来；执行器按注册表调用真实处理函数。\n5. 用独立答案检验规则是否有效，再接真实数据。不能用本数据生成的表现承诺真实准确率。\n`, 'utf8');
console.log(JSON.stringify({ output: OUT, files: catalog.length, rows: catalog.reduce((a, c) => a + c.rows, 0), checks: checks.length,
  selected_relay_post_reroute_utilization_pct: rerouteReference.selected_relay_demand_utilization_pct,
  initial_status_counts: cases.map(c => ({ case_id: c.case_id,
    major: overview.filter(x => x.case_id === c.case_id && x.initial_major_alert).length,
    watch: overview.filter(x => x.case_id === c.case_id && x.initial_watch).length })) }, null, 2));
