'use client';

import { useEffect, useMemo, useState } from 'react';
import { Button } from '@/components/ui/button';

type Robot = { id: string; x: number; y: number; tone: 'cyan' | 'magenta' | 'lime'; state: string };
type Frame = { robots: Robot[]; note: string; blocked?: boolean; partitioned?: boolean };
type Scenario = {
  label: string;
  short: string;
  verdict: string;
  metrics: [string, string][];
  frames: Frame[];
};

const scenarios: Record<string, Scenario> = {
  coordinated: {
    label: 'Distributed coordination',
    short: 'Peers lease the intersection before they move.',
    verdict: 'Reservations serialize only the shared zone—not the entire fleet.',
    metrics: [['Safety', '0 modeled conflicts'], ['Flow', 'concurrent outside zone'], ['Authority', 'robot-local']],
    frames: [
      { robots: [{ id: 'R1', x: 1, y: 3, tone: 'cyan', state: 'bidding' }, { id: 'R2', x: 5, y: 0, tone: 'magenta', state: 'bidding' }, { id: 'R3', x: 10, y: 3, tone: 'lime', state: 'routing' }], note: 'Peers publish short intent horizons.' },
      { robots: [{ id: 'R1', x: 3, y: 3, tone: 'cyan', state: 'zone held' }, { id: 'R2', x: 5, y: 1, tone: 'magenta', state: 'yielding' }, { id: 'R3', x: 9, y: 3, tone: 'lime', state: 'rerouting' }], note: 'R1 wins the lease; R2 yields; R3 selects a quieter edge.' },
      { robots: [{ id: 'R1', x: 5, y: 3, tone: 'cyan', state: 'moving' }, { id: 'R2', x: 5, y: 1, tone: 'magenta', state: 'committed' }, { id: 'R3', x: 8, y: 4, tone: 'lime', state: 'moving' }], note: 'Only one robot enters the conflict zone.' },
      { robots: [{ id: 'R1', x: 7, y: 3, tone: 'cyan', state: 'released' }, { id: 'R2', x: 5, y: 3, tone: 'magenta', state: 'moving' }, { id: 'R3', x: 7, y: 5, tone: 'lime', state: 'moving' }], note: 'R1 releases; R2 enters immediately; R3 never stops.' },
      { robots: [{ id: 'R1', x: 10, y: 3, tone: 'cyan', state: 'tasking' }, { id: 'R2', x: 5, y: 5, tone: 'magenta', state: 'tasking' }, { id: 'R3', x: 4, y: 5, tone: 'lime', state: 'tasking' }], note: 'The rest of the warehouse keeps moving.' },
    ],
  },
  baseline: {
    label: 'Stop-and-wait baseline',
    short: 'Robots react only when they reach the conflict.',
    verdict: 'Safe can still be slow: every local stop becomes fleet-wide queueing.',
    metrics: [['Safety', 'reactive stops'], ['Flow', 'serialized approach'], ['Authority', 'local but myopic']],
    frames: [
      { robots: [{ id: 'R1', x: 1, y: 3, tone: 'cyan', state: 'shortest path' }, { id: 'R2', x: 5, y: 0, tone: 'magenta', state: 'shortest path' }, { id: 'R3', x: 10, y: 3, tone: 'lime', state: 'shortest path' }], note: 'All three choose the same shortest crossing.' },
      { robots: [{ id: 'R1', x: 4, y: 3, tone: 'cyan', state: 'braking' }, { id: 'R2', x: 5, y: 2, tone: 'magenta', state: 'braking' }, { id: 'R3', x: 6, y: 3, tone: 'lime', state: 'braking' }], note: 'Conflict appears late; everyone brakes.' },
      { robots: [{ id: 'R1', x: 5, y: 3, tone: 'cyan', state: 'moving' }, { id: 'R2', x: 5, y: 2, tone: 'magenta', state: 'waiting' }, { id: 'R3', x: 6, y: 3, tone: 'lime', state: 'waiting' }], note: 'R1 moves. R2 and R3 remain idle.' },
      { robots: [{ id: 'R1', x: 8, y: 3, tone: 'cyan', state: 'moving' }, { id: 'R2', x: 5, y: 3, tone: 'magenta', state: 'moving' }, { id: 'R3', x: 6, y: 3, tone: 'lime', state: 'waiting' }], note: 'R2 moves next; the queue persists.' },
      { robots: [{ id: 'R1', x: 10, y: 3, tone: 'cyan', state: 'done' }, { id: 'R2', x: 5, y: 5, tone: 'magenta', state: 'done' }, { id: 'R3', x: 3, y: 3, tone: 'lime', state: 'moving' }], note: 'R3 finally clears the crossing.' },
    ],
  },
  blocked: {
    label: 'Blocked aisle',
    short: 'A dropped pallet invalidates the cheapest route.',
    verdict: 'One local incident changes peer costs before it creates a second jam.',
    metrics: [['Safety', 'edge quarantined'], ['Flow', 'local reroute'], ['AI role', 'predict delay']],
    frames: [
      { robots: [{ id: 'R1', x: 1, y: 3, tone: 'cyan', state: 'moving' }, { id: 'R2', x: 5, y: 0, tone: 'magenta', state: 'moving' }, { id: 'R3', x: 9, y: 5, tone: 'lime', state: 'moving' }], note: 'Normal motion with current map digest.' },
      { robots: [{ id: 'R1', x: 3, y: 3, tone: 'cyan', state: 'incident' }, { id: 'R2', x: 5, y: 1, tone: 'magenta', state: 'replanning' }, { id: 'R3', x: 8, y: 5, tone: 'lime', state: 'replanning' }], note: 'R1 detects a pallet and publishes a blocked-edge incident.', blocked: true },
      { robots: [{ id: 'R1', x: 3, y: 4, tone: 'cyan', state: 'rerouting' }, { id: 'R2', x: 6, y: 1, tone: 'magenta', state: 'rerouting' }, { id: 'R3', x: 7, y: 5, tone: 'lime', state: 'moving' }], note: 'Peers reweight routes; no one enters the blocked segment.', blocked: true },
      { robots: [{ id: 'R1', x: 4, y: 5, tone: 'cyan', state: 'moving' }, { id: 'R2', x: 8, y: 2, tone: 'magenta', state: 'moving' }, { id: 'R3', x: 5, y: 5, tone: 'lime', state: 'zone held' }], note: 'Traffic splits across two alternate paths.', blocked: true },
      { robots: [{ id: 'R1', x: 8, y: 5, tone: 'cyan', state: 'tasking' }, { id: 'R2', x: 10, y: 3, tone: 'magenta', state: 'tasking' }, { id: 'R3', x: 3, y: 5, tone: 'lime', state: 'tasking' }], note: 'The blocked edge stays quarantined until verified clear.', blocked: true },
    ],
  },
  partition: {
    label: 'Network partition',
    short: 'R2 loses fresh peer agreement near the crossing.',
    verdict: 'The design sacrifices liveness at one robot to preserve fleet safety.',
    metrics: [['Safety', 'safe-stop'], ['Flow', 'degraded, not dead'], ['Recovery', 'epoch reconcile']],
    frames: [
      { robots: [{ id: 'R1', x: 1, y: 3, tone: 'cyan', state: 'moving' }, { id: 'R2', x: 5, y: 0, tone: 'magenta', state: 'moving' }, { id: 'R3', x: 10, y: 3, tone: 'lime', state: 'moving' }], note: 'All peer heartbeats are fresh.' },
      { robots: [{ id: 'R1', x: 3, y: 3, tone: 'cyan', state: 'committed' }, { id: 'R2', x: 5, y: 1, tone: 'magenta', state: 'stale peers' }, { id: 'R3', x: 8, y: 3, tone: 'lime', state: 'committed' }], note: 'R2 loses peer freshness before acquiring the zone.', partitioned: true },
      { robots: [{ id: 'R1', x: 5, y: 3, tone: 'cyan', state: 'moving' }, { id: 'R2', x: 5, y: 1, tone: 'magenta', state: 'safe stop' }, { id: 'R3', x: 8, y: 4, tone: 'lime', state: 'rerouting' }], note: 'R2 stops at a safe node. Existing verified commitments continue.', partitioned: true },
      { robots: [{ id: 'R1', x: 8, y: 3, tone: 'cyan', state: 'moving' }, { id: 'R2', x: 5, y: 1, tone: 'magenta', state: 'reconciling' }, { id: 'R3', x: 7, y: 5, tone: 'lime', state: 'moving' }], note: 'Connection returns; R2 discards expired proposals and reconciles epochs.' },
      { robots: [{ id: 'R1', x: 10, y: 3, tone: 'cyan', state: 'tasking' }, { id: 'R2', x: 5, y: 3, tone: 'magenta', state: 'moving' }, { id: 'R3', x: 3, y: 5, tone: 'lime', state: 'tasking' }], note: 'R2 replans from current state and rejoins safely.' },
    ],
  },
};

const layers = [
  { key: 'assign', number: '01', title: 'Auction the work', copy: 'Robots score tasks by predicted finish time, congestion, battery, deadline and fairness. Claims expire unless renewed.' },
  { key: 'plan', number: '02', title: 'Plan in space + time', copy: 'Each robot runs A* against peer reservations—not only the warehouse geometry.' },
  { key: 'lease', number: '03', title: 'Lease the choke point', copy: 'Intersections and narrow aisles become named resources with buffered entry windows.' },
  { key: 'inherit', number: '04', title: 'Inherit priority', copy: 'Blocked priority propagates through a local wait chain; one robot backs to a pull-out instead of freezing the fleet.' },
  { key: 'shield', number: '05', title: 'Shield every move', copy: 'Stale peer state, conflicting intervals, missing leases or local obstacles force a deterministic slow/stop.' },
];

const algorithmRows = [
  ['Independent A*', 'Distributed', 'Fast', 'None', 'Baseline only'],
  ['CBS / EECBS', 'Centralized', 'Medium–slow', 'Strong in model', 'Small oracle'],
  ['RHCR', 'Centralized', 'Fast horizon', 'Window-dependent', 'Inspiration'],
  ['PIBT', 'Local-capable', 'Very fast', 'Conditional graph proof', 'Core idea'],
  ['Pure MARL', 'Distributed', 'Fast inference', 'No hard guarantee', 'Reject for safety'],
  ['SwarmRoute hybrid', 'Distributed', 'Bounded local', 'Hard shield + leases', 'Build'],
];

const failures = [
  ['Head-on swap', 'Reserve directed edge + time; deny opposite overlap.'],
  ['Circular deadlock', 'Detect wait-for cycle; inherit priority; backtrack one victim.'],
  ['Livelock', 'Hash repeated local state; change ordering or small-group repair.'],
  ['Robot dies', 'Freeze occupied zone; expire pre-pickup task lease; re-auction.'],
  ['Packet reordering', 'Boot ID + monotonic sequence + epoch; ignore older state.'],
  ['Partition', 'Finish verified commitment, then stop before contested zone.'],
  ['Clock / motion delay', 'Buffered intervals plus local progress confirmation.'],
  ['AI fails', 'Timeout to deterministic edge costs; shield remains unchanged.'],
];

const sources = [
  ['LSMART (2026)', 'https://arxiv.org/abs/2602.15721', 'realistic lifelong AGV testbed'],
  ['Robust path execution (2026)', 'https://doi.org/10.1016/j.artint.2026.104586', 'timing uncertainty and safe concurrency'],
  ['Many-to-Many MAPD (2026)', 'https://arxiv.org/abs/2605.07835', 'multiple valid SKU locations'],
  ['SMART (2025/26)', 'https://arxiv.org/abs/2503.04798', 'kinodynamics and execution uncertainty'],
  ['SILLM (ICRA 2025)', 'https://arxiv.org/abs/2410.21415', 'learning inside structured coordination'],
  ['WinC-MAPF (AAAI 2025)', 'https://arxiv.org/abs/2410.01798', 'windowed completeness and livelock'],
  ['Guidance graph optimization (2024)', 'https://doi.org/10.1609/aaai.v38i18.30054', 'optimize traffic, not just paths'],
  ['Real dynamics + tasks (2024)', 'https://arxiv.org/abs/2408.14527', 'warehouse task/trajectory coupling'],
  ['PIBT (IJCAI 2019)', 'https://doi.org/10.24963/ijcai.2019/76', 'local priority inheritance'],
  ['RHCR (AAAI 2021)', 'https://doi.org/10.1609/aaai.v35i13.17344', 'lifelong warehouse planning'],
  ['POGEMA (ICLR 2025)', 'https://proceedings.iclr.cc/paper_files/paper/2025/hash/10d19888a94f390e58f922ab3937e1cb-Abstract-Conference.html', 'reproducible learning/search benchmark'],
  ['Open-RMF architecture', 'https://osrf.github.io/ros2multirobotbook/rmf-core.html', 'reference and central-schedule distinction'],
];

function Window({ title, tone = 'blue', children, className = '' }: { title: string; tone?: 'blue' | 'red' | 'green'; children: React.ReactNode; className?: string }) {
  return (
    <section className={`window ${className}`}>
      <div className={`titlebar ${tone}`}><span>{title}</span><span aria-hidden="true">_ □ ×</span></div>
      <div className="window-body">{children}</div>
    </section>
  );
}

export default function Home() {
  const [scenarioKey, setScenarioKey] = useState('coordinated');
  const [frameIndex, setFrameIndex] = useState(0);
  const [running, setRunning] = useState(false);
  const [activeLayer, setActiveLayer] = useState('assign');
  const [failureOpen, setFailureOpen] = useState(0);
  const scenario = scenarios[scenarioKey];
  const frame = scenario.frames[frameIndex];

  useEffect(() => {
    if (!running) return;
    const timer = window.setInterval(() => {
      setFrameIndex((current) => {
        if (current >= scenario.frames.length - 1) {
          setRunning(false);
          return current;
        }
        return current + 1;
      });
    }, 850);
    return () => window.clearInterval(timer);
  }, [running, scenario.frames.length]);

  const activeLayerCopy = useMemo(() => layers.find((layer) => layer.key === activeLayer) ?? layers[0], [activeLayer]);
  const rackCells = useMemo(() => new Set(['1-1','2-1','3-1','7-1','8-1','9-1','1-5','2-5','3-5','7-5','8-5','9-5','1-6','2-6','3-6','7-6','8-6','9-6']), []);

  function changeScenario(key: string) {
    setScenarioKey(key);
    setFrameIndex(0);
    setRunning(false);
  }

  return (
    <main>
      <header className="site-header">
        <a className="brand" href="#top"><span className="brand-mark">SR</span><span>SwarmRoute Research Lab</span></a>
        <nav aria-label="Primary navigation">
          <a href="#simulator">[ simulation ]</a>
          <a href="#solution">[ solution ]</a>
          <a href="#evidence">[ research ]</a>
          <a href="#plan">[ team plan ]</a>
        </nav>
      </header>

      <div className="ticker" role="status"><span>*** SIH26123 FIELD NOTES // 2,879 SOURCES INDEXED // 50 CURATED REFERENCES // SAFETY ≠ AI // UPDATED 02-SEP-2026 ***</span></div>

      <section className="hero" id="top">
        <div className="eyebrow">Bharat Electronics Limited · SIH 2026 · Robotics &amp; Drones</div>
        <h1>Every robot gets a brain.<br />The warehouse keeps moving.</h1>
        <p className="lede">A distributed edge coordination system for warehouse AMRs that reserves conflict zones, negotiates locally, and degrades safely when Wi-Fi or a central service disappears.</p>
        <div className="hero-actions">
          <a className="win-button primary" href="#simulator">▶ Run the fleet stress test</a>
          <a className="win-button" href="#verdict">Read the verdict</a>
        </div>
        <p className="microcopy">Challenge target: ≥3 robots · 0 inter-robot collisions · ≥20% faster than stop-and-wait</p>
      </section>

      <section className="quick-verdict" id="verdict">
        <Window title="RESEARCH_VERDICT.TXT" tone="green" className="verdict-main">
          <p className="stamp">BUILD THIS</p>
          <h2>Deterministic safety. Distributed decisions. Learning in the passenger seat.</h2>
          <p>Use a distributed task auction, local space-time A*, short reservation leases and PIBT-style priority inheritance. Put a small congestion/ETA model on every robot—but never let it authorize motion.</p>
        </Window>
        <Window title="DO_NOT_BUILD.EXE" tone="red" className="reject-window">
          <ul className="cross-list">
            <li>✕ end-to-end MARL safety</li>
            <li>✕ one central SQL brain</li>
            <li>✕ full Open-RMF first</li>
            <li>✕ blockchain / LLM theatre</li>
            <li>✕ fake “production-ready” claims</li>
          </ul>
        </Window>
      </section>

      <section className="section-shell" id="simulator">
        <div className="section-heading">
          <p className="section-kicker">INTERACTIVE EXPLAINER</p>
          <h2>What changes when the world goes wrong?</h2>
          <p>Select a case, then play the five-step replay. This is an illustrative protocol visual—not a benchmark result.</p>
        </div>
        <Window title="SWARMROUTE_SIMULATOR.V1" className="sim-window">
          <div className="scenario-tabs" role="tablist" aria-label="Simulation scenario">
            {Object.entries(scenarios).map(([key, item]) => (
              <Button key={key} type="button" className={`retro-tab ${scenarioKey === key ? 'selected' : ''}`} aria-selected={scenarioKey === key} role="tab" onClick={() => changeScenario(key)}>{item.label}</Button>
            ))}
          </div>
          <div className="sim-layout">
            <div className="warehouse" aria-label={`Warehouse replay: ${scenario.label}`}>
              <div className="warehouse-grid" aria-hidden="true">
                {Array.from({ length: 84 }, (_, index) => {
                  const x = index % 12;
                  const y = Math.floor(index / 12);
                  return <span className={rackCells.has(`${x}-${y}`) ? 'rack' : ''} key={index} />;
                })}
              </div>
              <div className="zone-mark">ZONE A</div>
              {frame.blocked && <div className="obstacle" aria-label="Blocked aisle">PALLET</div>}
              {frame.partitioned && <div className="partition-signal" aria-label="Network partition">NO LINK</div>}
              {frame.robots.map((robot) => (
                <div key={robot.id} className={`sim-robot ${robot.tone}`} style={{ '--robot-x': robot.x, '--robot-y': robot.y } as React.CSSProperties}>
                  <strong>{robot.id}</strong><span>{robot.state}</span>
                </div>
              ))}
            </div>
            <aside className="sim-console">
              <p className="console-label">CASE FILE</p>
              <h3>{scenario.label}</h3>
              <p>{scenario.short}</p>
              <dl className="metric-list">
                {scenario.metrics.map(([label, value]) => <div key={label}><dt>{label}</dt><dd>{value}</dd></div>)}
              </dl>
              <div className="sim-actions">
                <Button type="button" className="win-button primary" onClick={() => { if (frameIndex >= scenario.frames.length - 1) setFrameIndex(0); setRunning(true); }} disabled={running}>▶ {running ? 'Running…' : 'Play replay'}</Button>
                <Button type="button" className="win-button" onClick={() => { setRunning(false); setFrameIndex(0); }}>↺ Reset</Button>
              </div>
              <div className="step-dots" aria-label={`Step ${frameIndex + 1} of ${scenario.frames.length}`}>
                {scenario.frames.map((_, index) => <button key={index} type="button" aria-label={`Go to step ${index + 1}`} className={index === frameIndex ? 'active' : ''} onClick={() => { setRunning(false); setFrameIndex(index); }} />)}
              </div>
            </aside>
          </div>
          <div className="event-log" aria-live="polite"><strong>STEP {frameIndex + 1}/{scenario.frames.length}</strong> {frame.note}</div>
          <p className="sim-verdict"><strong>Design lesson:</strong> {scenario.verdict}</p>
        </Window>
      </section>

      <section className="section-shell" id="solution">
        <div className="section-heading">
          <p className="section-kicker">THE FIVE-LAYER BUILD</p>
          <h2>No magic algorithm. A safety-shaped stack.</h2>
        </div>
        <div className="layer-rail" role="tablist" aria-label="Architecture layer">
          {layers.map((layer) => (
            <button type="button" key={layer.key} className={activeLayer === layer.key ? 'active' : ''} onClick={() => setActiveLayer(layer.key)} role="tab" aria-selected={activeLayer === layer.key}>
              <span>{layer.number}</span><strong>{layer.title}</strong>
            </button>
          ))}
        </div>
        <Window title={`${activeLayerCopy.number}_${activeLayerCopy.title.toUpperCase().replaceAll(' ', '_')}.TXT`} className="layer-detail">
          <div className="layer-copy"><span className="big-number">{activeLayerCopy.number}</span><div><h3>{activeLayerCopy.title}</h3><p>{activeLayerCopy.copy}</p></div></div>
        </Window>
        <div className="architecture-map" aria-label="Distributed fleet architecture">
          {['AMR-01', 'AMR-02', 'AMR-03'].map((robot, index) => (
            <article className="robot-node" key={robot}><i className={`status-light light-${index + 1}`} /><strong>{robot}</strong><span>task auction</span><span>space-time A*</span><span>intent ledger</span><span>safety shield</span></article>
          ))}
          <div className="peer-band">← intent · bids · leases · incidents →</div>
          <article className="observer-node"><strong>MONITOR ONLY</strong><span>dashboard + telemetry</span><em>kill it; robots continue</em></article>
        </div>
      </section>

      <section className="section-shell compare-section">
        <div className="section-heading"><p className="section-kicker">WHY THIS APPROACH</p><h2>The useful algorithm is the one we can defend.</h2></div>
        <Window title="ALGORITHM_SCORECARD.XLS" className="score-window">
          <div className="table-wrap">
            <table>
              <thead><tr><th>Method</th><th>Control</th><th>Decision speed</th><th>Safety story</th><th>Verdict</th></tr></thead>
              <tbody>{algorithmRows.map((row) => <tr key={row[0]}>{row.map((cell, index) => <td key={cell} className={index === 4 && cell === 'Build' ? 'build-cell' : ''}>{cell}</td>)}</tr>)}</tbody>
            </table>
          </div>
          <p className="table-note">PIBT’s finite-arrival proof is conditional on graph structure. We therefore add explicit corridor leases, pull-outs, aging and repeated-state recovery.</p>
        </Window>
      </section>

      <section className="evidence-section" id="evidence">
        <div className="section-heading"><p className="section-kicker">AUDITABLE RESEARCH</p><h2>Broad discovery. Aggressive filtering. No bibliography padding.</h2></div>
        <div className="corpus-stats">
          <div><strong>2,879</strong><span>deduplicated records</span></div>
          <div><strong>1,212</strong><span>published since 2023</span></div>
          <div><strong>250</strong><span>screening shortlist</span></div>
          <div><strong>50</strong><span>curated core references</span></div>
        </div>
        <div className="evidence-grid">
          <Window title="METHOD_README.TXT">
            <ol className="method-list"><li>Eight OpenAlex discovery queries from 2015 onward.</li><li>Deduplicate by work ID; retain raw responses.</li><li>Favor 2024–2026 direct-title matches.</li><li>Check claims against papers and official repos.</li><li>Use community posts only for integration anecdotes.</li></ol>
            <p className="honesty-box">2,879 indexed ≠ 2,879 deeply read. The corpus is an auditable discovery layer; the 50-source bibliography drives decisions.</p>
          </Window>
          <Window title="FRONTIER_2026.URL" tone="green">
            <ul className="link-list">
              {sources.slice(0, 6).map(([title, url, note]) => <li key={title}><a href={url} target="_blank" rel="noreferrer">{title}</a><span>{note}</span></li>)}
            </ul>
          </Window>
        </div>
        <Window title="CURATED_EVIDENCE_LIBRARY.URL" className="source-window">
          <div className="source-grid">
            {sources.map(([title, url, note]) => <a href={url} target="_blank" rel="noreferrer" key={title}><strong>{title}</strong><span>{note}</span></a>)}
          </div>
          <p className="source-note">Full DOI-linked bibliography, open-source license notes and the 2,879-record CSV live in the project’s research dossier.</p>
        </Window>
      </section>

      <section className="section-shell failure-section">
        <div className="section-heading"><p className="section-kicker">FAILURE IS A FEATURE</p><h2>Design the ugly cases before demo day.</h2><p>Open a case to see the required response. None of these may depend on the dashboard.</p></div>
        <div className="failure-grid">
          {failures.map(([title, response], index) => (
            <button type="button" key={title} className={failureOpen === index ? 'open' : ''} onClick={() => setFailureOpen(index)} aria-pressed={failureOpen === index}>
              <span className="error-icon">{failureOpen === index ? '!' : '?'}</span><strong>{title}</strong><span>{failureOpen === index ? response : 'Click for response'}</span>
            </button>
          ))}
        </div>
        <div className="fault-strip">TEST: same-cell · edge-swap · rear-end delay · rotation overlap · starvation · stale map · duplicate task · robot-in-zone crash · 50% burst loss · 1s latency · split partition · AI timeout</div>
      </section>

      <section className="measurement-section">
        <div className="section-heading"><p className="section-kicker">HOW WE PROVE IT</p><h2>Same seed. Same workload. Paired evidence.</h2></div>
        <div className="measurement-grid">
          <Window title="BASELINES.TXT"><ol><li>Stop-and-wait</li><li>Independent A*</li><li>Distributed, fixed cost</li><li>Distributed + heatmap</li><li>Distributed + learned ETA</li></ol></Window>
          <Window title="MEASUREMENTS.TXT"><ol><li>Tasks/min + total completion time</li><li>p95/max task time and wait</li><li>Executed vs rejected conflicts</li><li>Recovery time + orphan tasks</li><li>p95 planner/model latency</li></ol></Window>
          <Window title="CLAIM_POLICY.TXT" tone="red"><p>Never say “zero collisions everywhere.” Say: <strong>zero modeled conflicts across N seeded trials under declared kinematic and network assumptions.</strong></p><p className="formula">gain = (baseline − proposed) / baseline × 100</p></Window>
        </div>
      </section>

      <section className="plan-section" id="plan">
        <div className="section-heading"><p className="section-kicker">6 PEOPLE · 36 HOURS</p><h2>Four technical owners. One vertical demo.</h2></div>
        <div className="team-grid">
          {[
            ['01', 'Lead / generalist', 'protocol · safety shield · integration'],
            ['02', 'Python A', 'auctions · leases · failure recovery'],
            ['03', 'Python B', 'A* · reservations · deadlocks'],
            ['04', 'SQL / data', 'event log · replay · metrics · model data'],
            ['05', 'QA / evidence', 'fault matrix · citations · backup video'],
            ['06', 'Story / UI', 'dashboard · pitch · judge flow'],
          ].map(([number, title, work]) => <article key={number}><span>{number}</span><strong>{title}</strong><p>{work}</p></article>)}
        </div>
        <Window title="HACKATHON_TIMELINE.BAT" className="timeline-window">
          <div className="timeline">
            {[
              ['00–03', 'Freeze contracts'], ['03–10', 'Tracer bullet'], ['10–18', 'Coordination core'], ['18–24', 'Failure semantics'], ['24–28', 'Edge model'], ['28–32', 'Evidence freeze'], ['32–35', 'Pitch + backup'], ['35–36', 'Bug buffer'],
            ].map(([time, label], index) => <div key={time} className={index < 3 ? 'critical' : ''}><strong>{time}h</strong><span>{label}</span></div>)}
          </div>
          <p className="timeline-note">Stretch order: better metrics → 3–6 robot Nav2/Gazebo adapter → many-to-many SKU locations → ONNX. Do not start with physics or full Open-RMF.</p>
        </Window>
      </section>

      <section className="demo-script">
        <div className="section-heading"><p className="section-kicker">THE FIVE-MINUTE JUDGE STORY</p><h2>Make decentralization visible.</h2></div>
        <div className="demo-steps">
          {['Show stop-and-wait queueing', 'Switch on auctions + leases', 'Drop a pallet; peers reroute', 'Disconnect a robot; it safe-stops', 'Kill dashboard; fleet continues', 'End on paired metrics + ablation'].map((step, index) => <div key={step}><span>0{index + 1}</span><p>{step}</p></div>)}
        </div>
        <blockquote>“AI predicts cost and risk. Deterministic state machines enforce safety.”</blockquote>
      </section>

      <footer>
        <div><strong>SWARMROUTE / SIH26123</strong><span>research snapshot · 02 September 2026</span></div>
        <div><a href="#top">back to top ↑</a><span className="visitor">visitor no. 002879</span></div>
      </footer>
    </main>
  );
}
