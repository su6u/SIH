export interface Frame { t: number; x: number; z: number; yaw: number; battery: number; status: string; task: string; load: boolean }
export interface RobotTrace { id: string; name: string; color: string; frames: Frame[] }
export interface Metric { t: number; completed: number; active: number; queued: number; throughput: number; avgBattery: number; distance: number; conflicts: number; replans: number }
export interface Incident { tick: number; type: string; title: string; description: string; cell: [number, number] }
export interface TimedObstacle { fromTick: number; toTick: number; cells: [number, number][]; label: string }
export interface Summary { completed: number; conflicts: number; replans: number; distance: number; robots: number }
export interface SimulationEvent { tick: number; kind: string; entityId: string; data: Record<string, unknown> }
export interface Grid { width: number; height: number; blocked: [number, number][] }
export interface Scenario { schemaVersion: string; id: string; title: string; subtitle: string; kind: string; duration: number; tickSeconds: number; grid: Grid; incidents: Incident[]; obstacles: TimedObstacle[]; robots: RobotTrace[]; metrics: Metric[]; events: SimulationEvent[]; summary: Summary }
export interface ScenarioMeta { id: string; title: string; subtitle: string; file: string; summary: Summary }
export interface Manifest { schemaVersion: string; default: string; scenarios: ScenarioMeta[] }
