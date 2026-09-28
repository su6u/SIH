import * as THREE from "three";
import { GLTFLoader } from "three/addons/loaders/GLTFLoader.js";
import { MeshoptDecoder } from "three/addons/libs/meshopt_decoder.module.js";
import { OrbitControls } from "three/addons/controls/OrbitControls.js";
import { clone as cloneSkeleton } from "three/addons/utils/SkeletonUtils.js";
import { RoomEnvironment } from "three/addons/environments/RoomEnvironment.js";
import { Line2 } from "three/addons/lines/Line2.js";
import { LineGeometry } from "three/addons/lines/LineGeometry.js";
import { LineMaterial } from "three/addons/lines/LineMaterial.js";
import "./style.css";
import { woodFloor } from "./floor";
import { createHazardMarker, createWarehouse } from "./warehouse";
import type { Frame, Manifest, RobotTrace, Scenario, SimulationEvent } from "./types";

const q = <T extends HTMLElement>(selector: string) => document.querySelector<T>(selector)!;
const canvas = q<HTMLCanvasElement>("#world");
const playButton = q<HTMLButtonElement>("#play");
const timeline = q<HTMLElement>("#timeline");
const timelinePreview = q<HTMLOutputElement>("#timeline-preview");
const gltfLoader = new GLTFLoader().setMeshoptDecoder(MeshoptDecoder);
const renderer = new THREE.WebGLRenderer({ canvas, antialias: true, powerPreference: "high-performance", alpha: false });
// A 2.5x backing buffer is disproportionately expensive on presentation laptops.
// 1.5x is still retina-sharp while leaving GPU time for the full-detail scene.
const presentationPixelRatio = () => Math.min(window.devicePixelRatio || 1, 1.5);
renderer.setPixelRatio(presentationPixelRatio());
renderer.setSize(innerWidth, innerHeight);
renderer.shadowMap.enabled = true;
renderer.shadowMap.type = THREE.PCFSoftShadowMap;
renderer.outputColorSpace = THREE.SRGBColorSpace;
renderer.toneMapping = THREE.ACESFilmicToneMapping;
renderer.toneMappingExposure = .7;
// Transmitted glass is retained, but its internal buffer does not need to match
// the full canvas resolution to look clear through the roof and facade.
renderer.transmissionResolutionScale = .5;

const scene = new THREE.Scene();
scene.background = new THREE.Color(0x191919);
scene.fog = null;
const floorMaterial = woodFloor();
const environment = new THREE.PMREMGenerator(renderer).fromScene(new RoomEnvironment(), .04).texture;
scene.environment = environment;
const camera = new THREE.PerspectiveCamera(43, innerWidth / innerHeight, .1, 520);
camera.position.set(92, 42, 62);
const controls = new OrbitControls(camera, canvas);
controls.enableDamping = true;
controls.dampingFactor = .055;
controls.target.set(27, 1.1, -20);
controls.minPolarAngle = .08;
controls.maxPolarAngle = 1.48;
controls.minDistance = 4;
controls.maxDistance = 150;
controls.enablePan = true;
controls.screenSpacePanning = true;

const birdCamera = new THREE.OrthographicCamera(-Math.max(54,36*innerWidth/innerHeight), Math.max(54,36*innerWidth/innerHeight), Math.max(36,54*innerHeight/innerWidth), -Math.max(36,54*innerHeight/innerWidth), .1, 220);
birdCamera.position.set(27, 92, -20);
birdCamera.up.set(0, 0, -1);
birdCamera.lookAt(27, 0, -20);
birdCamera.zoom = 1;
birdCamera.updateProjectionMatrix();
const birdControls = new OrbitControls(birdCamera, canvas);
birdControls.enableDamping = true;
birdControls.dampingFactor = .08;
birdControls.enableRotate = false;
birdControls.screenSpacePanning = true;
birdControls.minZoom = .65;
birdControls.maxZoom = 3.2;
birdControls.target.set(27, 0, -20);

function activeCamera(): THREE.Camera {
  return cameraMode === "bird" ? birdCamera : camera;
}

const { world: fallbackWarehouse } = createWarehouse(scene);
fallbackWarehouse.scale.z = -1;
fallbackWarehouse.traverse(object => {
  if (object instanceof THREE.Mesh) {
    const name = object.name.toLowerCase();
    object.castShadow = /rack|column|purlin|plinth|parapet|slab|floor|dock/.test(name);
    object.receiveShadow = true;
    if (/polished concrete/.test(name)) object.material = floorMaterial;
    object.updateMatrix();
    object.matrixAutoUpdate = false;
  }
});
renderer.shadowMap.autoUpdate = false;
renderer.shadowMap.needsUpdate = true;
const floorOverlay = new THREE.Group();
floorOverlay.name = "continuous oak floor";
const floorSections: [number, number, number, number][] = [
  [90, 42, 27, -9],
  [78, 12, 21, -36],
  [30, 12, -3, -48],
];
for (const [width, depth, x, z] of floorSections) {
  const section = new THREE.Mesh(new THREE.BoxGeometry(width, .04, depth), floorMaterial);
  section.name = "oak floor overlay";
  section.position.set(x, .02, z);
  section.receiveShadow = true;
  floorOverlay.add(section);
}
scene.add(floorOverlay);
const fleet = new THREE.Group(); fleet.name = "live fleet"; scene.add(fleet);
const routes = new THREE.Group(); routes.name = "route overlays"; scene.add(routes);
const hazard = createHazardMarker(); scene.add(hazard);
const peerOverlay = new THREE.Group(); peerOverlay.name = "peer message overlay"; scene.add(peerOverlay);
const incidentOverlay = new THREE.Group(); incidentOverlay.name = "incident overlay"; scene.add(incidentOverlay);
const comparisonOverlay = new THREE.Group(); comparisonOverlay.name = "uncoordinated comparison"; scene.add(comparisonOverlay);
const explanationOverlay = new THREE.Group(); explanationOverlay.name = "guided explanation cues"; scene.add(explanationOverlay);
const clock = new THREE.Clock();
let activePixelRatio = presentationPixelRatio();
let frameSampleSeconds = 0;
let frameSampleCount = 0;
const raycaster = new THREE.Raycaster();
const pointer = new THREE.Vector2();

let manifest: Manifest;
let scenario: Scenario;
let robotTemplate: THREE.Object3D;
let detailedWarehouse: THREE.Object3D | null = null;
let elapsedSeconds = 0;
let playing = true;
let playbackSpeed = 1;
let selectedId = "robot_01";
let cameraMode = "cinematic";
let lastRouteTick = -99;
let timelineDragging = false;
let timelinePointerId: number | null = null;

const robotObjects = new Map<string, THREE.Group>();
let compareMode: "without" | "with" = "with";
let comparisonSeconds = 0;
let introStartedAt = performance.now();
let introActive = true;
let directorShotKey = "";
let directorShotElapsed = 0;
const directorFromPosition = new THREE.Vector3();
const directorFromTarget = new THREE.Vector3();

let lastInterfaceUpdate = -1;
let activeConflictTick = 0;
let activeConflictPoint = new THREE.Vector3(27, .2, -20);
const peerLines: Line2[] = [];
const peerGlowLines: Line2[] = [];
let linksEnabled = true;
const blockerMeshes: THREE.Object3D[] = [];
const broadcastRings: THREE.Mesh[] = [];
const causalBaseLines: Line2[] = [];
const causalGlowLines: Line2[] = [];
const causalLines: Line2[] = [];
const peerNeighborCache = new Map<string, string[]>();
let explanationRing: THREE.Mesh | null = null;
let explanationLabel: THREE.Sprite | null = null;
let explanationKey = "";


function adaptPixelRatio(delta: number) {
  // Keep the authored geometry and materials at full detail. Only reduce the
  // canvas backing buffer when a slow GPU demonstrably needs headroom, then
  // restore the sharper buffer once the frame budget is healthy again.
  frameSampleSeconds += delta;
  frameSampleCount += 1;
  if (frameSampleSeconds < 2.5) return;
  const fps = frameSampleCount / frameSampleSeconds;
  const requested = presentationPixelRatio();
  const target = fps < 34 ? Math.min(requested, 1) : fps < 48 ? Math.min(requested, 1.25) : requested;
  if (Math.abs(target - activePixelRatio) > .01) {
    activePixelRatio = target;
    renderer.setPixelRatio(activePixelRatio);
  }
  frameSampleSeconds = 0;
  frameSampleCount = 0;
}

function simpleRobot() {
  const group = new THREE.Group();
  const mint = new THREE.MeshStandardMaterial({color:0x72dbcb,roughness:.3,metalness:.2});
  const dark = new THREE.MeshStandardMaterial({color:0x15272c,roughness:.38,metalness:.4});
  const body = new THREE.Mesh(new THREE.BoxGeometry(1.35,.5,1),mint); body.position.y=.48; body.castShadow=true; group.add(body);
  const top = new THREE.Mesh(new THREE.BoxGeometry(.78,.18,.7),dark); top.position.y=.83; group.add(top);
  for(const z of [-.55,.55]){const wheel=new THREE.Mesh(new THREE.CylinderGeometry(.25,.25,.16,18),dark);wheel.rotation.x=Math.PI/2;wheel.position.set(0,.28,z);group.add(wheel)}
  return group;
}

function robotTag(text: string, color: string) {
  const surface = document.createElement("canvas");
  surface.width = 512; surface.height = 112;
  const context = surface.getContext("2d")!;
  context.clearRect(0, 0, 512, 112);
  context.shadowColor = "#000000"; context.shadowBlur = 5;
  context.fillStyle = color; context.font = "700 30px ui-monospace, monospace";
  context.textAlign = "left"; context.textBaseline = "middle"; context.fillText(text, 58, 56);
  const texture = new THREE.CanvasTexture(surface);
  texture.colorSpace = THREE.SRGBColorSpace;
  const sprite = new THREE.Sprite(new THREE.SpriteMaterial({ map: texture, transparent: true, depthWrite: false, depthTest: false, toneMapped: false }));
  sprite.name = "peer identity tag";
  sprite.position.y = 1.6;
  sprite.scale.set(3.3, .72, 1);
  sprite.renderOrder = 8;
  return sprite;
}

async function loadWarehouseModel() {
  q("#loading-status").textContent = "Loading the full 2,192-object warehouse";
  try {
    const gltf = await gltfLoader.loadAsync("/models/warehouse-full.glb");
    detailedWarehouse = gltf.scene;
    detailedWarehouse.name = "full-detail authored warehouse";
    detailedWarehouse.traverse(object => {
      const name = object.name.toLowerCase();
      if (object instanceof THREE.Mesh) {
        // The warehouse is static. Let it receive the sun's shadow, but do not
        // render a second shadow pass for every rack bolt, carton, and label.
        // Dynamic robots use a lightweight contact shadow below instead.
        const glassSurface = name.includes("glass") || name.includes("glazing") || name.includes("skylight");
        object.castShadow = !glassSurface && /rack|column|purlin|plinth|parapet|slab|floor|dock/.test(name);
        object.receiveShadow = true;
        // Authored warehouse nodes never move during replay. Freeze their local
        // matrices after import so the renderer does not rebuild 1,300 transforms
        // on every frame.
        object.updateMatrix();
        object.matrixAutoUpdate = false;
        if (/^slab(?:\.|$)/.test(name)) object.material = floorMaterial;
        const materials = Array.isArray(object.material) ? object.material : [object.material];
        if (glassSurface) {
          materials.forEach(item => {
            item.transparent = true;
            item.opacity = Math.min(item.opacity, .32);
            item.depthWrite = false;
            if (item instanceof THREE.MeshStandardMaterial) {
              item.roughness = .08;
              item.metalness = 0;
              if (item instanceof THREE.MeshPhysicalMaterial) {
                item.transmission = .78;
                item.thickness = .16;
              }
            }
          });
        }
      }
    });
    scene.add(detailedWarehouse);
    detailedWarehouse.updateMatrixWorld(true);
    fallbackWarehouse.visible = false;
    // Structural shadows are now static because robot casters are disabled.
    // Render this map once and keep it for the whole deterministic replay.
    renderer.shadowMap.autoUpdate = false;
    renderer.shadowMap.needsUpdate = true;
    // All lights and the static warehouse are now resident; precompile shaders
    // before the loading veil is removed so the first cinematic frame is smooth.
    if ("compileAsync" in renderer) await renderer.compileAsync(scene, camera);
  } catch (error) {
    console.warn("Full warehouse unavailable; keeping procedural fallback", error);
  }
}

async function loadRobotModel() {
  q("#loading-status").textContent = "Loading detailed BUDDY robots";
  try {
    const gltf = await gltfLoader.loadAsync("/models/buddy.glb");
    const template = gltf.scene;
    template.updateMatrixWorld(true);
    const bounds = new THREE.Box3().setFromObject(template);
    const size = bounds.getSize(new THREE.Vector3());
    const scale = 1.3 / Math.hypot(size.x, size.z);
    template.scale.setScalar(scale);
    template.updateMatrixWorld(true);
    const scaled = new THREE.Box3().setFromObject(template);
    template.position.y -= scaled.min.y;
    template.traverse(object => {
      if (object instanceof THREE.Mesh) {
        object.castShadow = false;
        object.receiveShadow = false;
      }
    });
    return template;
  } catch (error) {
    console.warn("Detailed model unavailable; using presentation fallback", error);
    return simpleRobot();
  }
}

function makeRobotObject(trace: RobotTrace) {
  const wrapper = new THREE.Group();
  wrapper.name = `${trace.id} / ${trace.name}`;
  wrapper.userData.robotId = trace.id;
  const model = cloneSkeleton(robotTemplate);
  model.userData.robotId = trace.id;
  const accent = new THREE.Color(trace.color);
  // SkeletonUtils correctly clones hierarchy and geometry, but materials are
  // shared. Clone them per robot and recolour the authored enamel shell so the
  // browser presentation matches the scenario palette (the source GLB is mint).
  model.traverse(child => {
    if (!(child instanceof THREE.Mesh)) return;
    child.userData.sharedGeometry = true;
    const recolour = (source: THREE.Material) => {
      const copy = source.clone();
      copy.userData.kinesisClone = true;
      const materialName = copy.name.toLowerCase();
      if (materialName.includes("mint") || child.name.toLowerCase().includes("floating shell")) {
        const standard = copy as THREE.MeshStandardMaterial;
        if (standard.color) standard.color.copy(accent);
      }
      return copy;
    };
    child.material = Array.isArray(child.material) ? child.material.map(recolour) : recolour(child.material);
    child.castShadow = false;
    child.receiveShadow = false;
  });
  wrapper.add(model);
  rigWheels(model, wrapper);
  // A soft, camera-independent contact shadow keeps the high-poly robot
  // grounded without reintroducing 12 moving shadow-map casters.
  const contactShadow = new THREE.Mesh(
    new THREE.CircleGeometry(.64, 32),
    new THREE.MeshBasicMaterial({ color: 0x020607, transparent: true, opacity: .24, depthWrite: false }),
  );
  contactShadow.rotation.x = -Math.PI / 2;
  contactShadow.scale.set(1.18, .62, 1);
  contactShadow.position.y = .015;
  contactShadow.renderOrder = -1;
  contactShadow.name = "soft contact shadow";
  wrapper.add(contactShadow);
  const ringMaterial = new THREE.MeshBasicMaterial({color:trace.color,transparent:true,opacity:.85,side:THREE.DoubleSide,depthWrite:false});
  const ring = new THREE.Mesh(new THREE.RingGeometry(.7,.725,36),ringMaterial);
  ring.rotation.x=-Math.PI/2;ring.position.y=.07;ring.name="selection ring";ring.visible=false;wrapper.add(ring);
  wrapper.add(robotTag(`${trace.name.toLowerCase()} / ${trace.id.slice(-2)}`, trace.color));
  wrapper.traverse(child => child.userData.robotId = trace.id);
  return wrapper;
}

function rigWheels(model: THREE.Object3D, wrapper: THREE.Group) {
  model.updateMatrixWorld(true);
  const parts: THREE.Object3D[] = [];
  const tyres: THREE.Object3D[] = [];
  model.traverse(part => {
    if (/moulded tyre/.test(part.name)) tyres.push(part);
    if (/brushed wheel rim|moulded tyre|orange hubcap|tyre siping|wheel lug/.test(part.name)) parts.push(part);
  });
  const pivots = tyres.map(tyre => {
    const box = new THREE.Box3().setFromObject(tyre);
    const worldCenter = box.getCenter(new THREE.Vector3());
    const pivot = new THREE.Group();
    pivot.name = "wheel axle";
    pivot.position.copy(model.worldToLocal(worldCenter.clone()));
    pivot.userData.radius = box.getSize(new THREE.Vector3()).y / 2;
    pivot.userData.side = pivot.position.z > 0 ? 1 : -1;
    model.add(pivot);
    return pivot;
  });
  for (const part of parts) {
    const center = new THREE.Box3().setFromObject(part).getCenter(new THREE.Vector3());
    const pivot = [...pivots].sort((a,b) => a.getWorldPosition(new THREE.Vector3()).distanceToSquared(center)-b.getWorldPosition(new THREE.Vector3()).distanceToSquared(center))[0];
    pivot?.attach(part);
  }
  wrapper.userData.wheels = pivots;
}

function animateWheels(object: THREE.Group, trace: RobotTrace, tick: number) {
  const index = Math.min(Math.floor(tick), trace.frames.length - 1);
  let distance = 0, heading = 0;
  for (let i = 1; i <= Math.min(index + 1, trace.frames.length - 1); i++) {
    const a = trace.frames[i-1], b = trace.frames[i];
    const fraction = i > index ? tick - index : 1;
    distance += Math.hypot(b.x-a.x,b.z-a.z)*fraction;
    heading += Math.atan2(Math.sin(b.yaw-a.yaw),Math.cos(b.yaw-a.yaw))*fraction;
  }
  const wheels = object.userData.wheels as THREE.Group[] | undefined;
  wheels?.forEach(wheel => {
    wheel.rotation.z = -(distance + heading * .3 * Number(wheel.userData.side)) / Number(wheel.userData.radius);
  });
}

function robotGroupCenter(ids: string[], fallback: THREE.Vector3) {
  const positions = ids.map(id => robotObjects.get(id)?.position).filter((position): position is THREE.Vector3 => Boolean(position));
  if (!positions.length) return fallback.clone();
  return positions.reduce((sum, position) => sum.add(position), new THREE.Vector3()).multiplyScalar(1 / positions.length);
}

function rerouteActors() {
  for (const requeued of scenario.events.filter(event => event.kind === "task_requeued")) {
    const awarded = scenario.events.find(event => event.kind === "task_awarded" && event.entityId === requeued.entityId && event.tick >= requeued.tick);
    const previous = String(requeued.data.robot_id ?? "");
    const next = String(awarded?.data.robot_id ?? "");
    if (previous && next && previous !== next) return { previous, next };
  }
  return { previous: "robot_07", next: "robot_08" };
}

function updateDirector(delta: number) {
  const tick = elapsedSeconds / scenario.tickSeconds;
  let key = "warehouse-overview";
  let target = new THREE.Vector3(27, 0, -20);
  let offset = new THREE.Vector3(0, 54, 12);
  let caption = "warehouse / fleet overview";
  let tracksSubject = false;

  if (scenario.id === "peer-network") {
    const phase = Math.floor(tick / 18) % 3;
    const importantId = leadPeerAt(tick);
    const recipients = stableNearestRobotIds(importantId, 3, tick);
    if (phase === 0) {
      key = "peer-network-send";
      const peers = [importantId, ...recipients];
      target.copy(robotGroupCenter(peers, target));
      const span = Math.max(...peers.map(id => robotObjects.get(id)?.position.distanceTo(target) ?? 0));
      offset.set(0, THREE.MathUtils.clamp(span * 2.1, 24, 38), 6);
      caption = "network / sender and all three receivers";
      tracksSubject = true;
    } else if (phase === 1) {
      const relayId = recipients[0];
      const nextHops = stableNearestRobotIds(relayId ?? importantId, 2, tick, [importantId]);
      const peers = [importantId, relayId, ...nextHops].filter((id): id is string => Boolean(id));
      target.copy(robotGroupCenter(peers, target));
      const span = Math.max(...peers.map(id => robotObjects.get(id)?.position.distanceTo(target) ?? 0));
      key = "peer-message-exchange";
      offset.set(0, THREE.MathUtils.clamp(span * 2.15, 28, 46), 7);
      caption = `${importantId.replace("robot_", "peer ")} → ${relayId?.replace("robot_", "peer ") ?? "neighbor"} → two local peers`;
      tracksSubject = true;
    } else {
      key = "peer-task-agreement";
      target.copy(robotObjects.get(importantId)?.position ?? target);
      offset.set(0, 23, 5);
      caption = `${importantId.replace("robot_", "peer ")} / accepts winning bid`;
      tracksSubject = true;
    }
  } else if (scenario.id === "conflict-resolution") {
    if (compareMode === "without") {
      target.copy(activeConflictPoint);
      key = comparisonSeconds < 4.8 ? "conflict-converge" : "conflict-impact";
      offset.set(comparisonSeconds < 4.8 ? -9 : 0, comparisonSeconds < 4.8 ? 18 : 25, comparisonSeconds < 4.8 ? 11 : 2);
      caption = comparisonSeconds < 4.8 ? "without / all approaches visible" : "without / same space, same time";
    } else {
      const beat = conflictBeatAt(tick);
      const relativeTick = tick - beat.tick;
      const actors = importantConflictIds(beat.tick, beat.point);
      const winnerPosition = robotObjects.get(beat.winnerId)?.position ?? beat.point;
      const actorCenter = robotGroupCenter(actors, beat.point);
      const localSpan = Math.max(
        beat.point.distanceTo(actorCenter),
        ...actors.map(id => robotObjects.get(id)?.position.distanceTo(actorCenter) ?? 0),
      );
      if (relativeTick < -3) {
        key = `conflict-approach-${beat.key}`;
        target.copy(actorCenter).lerp(beat.point, .34);
        offset.set(-7, THREE.MathUtils.clamp(localSpan * 2, 22, 32), 10);
        caption = "with / peers approaching the next choke point";
      } else if (relativeTick < 4) {
        key = `conflict-reserve-${beat.key}`;
        target.copy(actorCenter).lerp(beat.point, .55);
        offset.set(0, THREE.MathUtils.clamp(localSpan * 2.15, 19, 30), 2);
        caption = "with / local right-of-way reservation";
      } else if (relativeTick < 11) {
        key = `conflict-release-${beat.key}`;
        target.copy(actorCenter).lerp(beat.point, .4);
        offset.set(-7, THREE.MathUtils.clamp(localSpan * 2.05, 19, 30), 8);
        caption = "with / winner clears, waiter remains outside";
      } else {
        key = `conflict-clear-${beat.key}`;
        target.copy(winnerPosition);
        offset.set(-8, 14, 9);
        caption = "with / granted robot continues to its task";
      }
      tracksSubject = true;
    }
  } else {
    const incident = scenario.incidents[0];
    const incidentTick = incident?.tick ?? 35;
    const blocked = incident ? new THREE.Vector3(-15 + incident.cell[0] * 1.5, 0, -(-9 + incident.cell[1] * 1.5)) : target;
    const actors = rerouteActors();
    if (tick < incidentTick) {
      key = "reroute-context";
      target.copy(blocked);
      offset.set(-10, 20, 13);
      caption = "aisle / assigned robot approaching";
    } else if (tick < incidentTick + 5) {
      key = "reroute-detected";
      target.copy(blocked);
      offset.set(0, 24, 2);
      caption = "blocked / current route invalidated";
    } else if (tick < incidentTick + 16) {
      key = "reroute-handoff";
      target.copy(robotGroupCenter([actors.previous, actors.next], blocked));
      const actorSpan = robotObjects.get(actors.previous)?.position.distanceTo(robotObjects.get(actors.next)?.position ?? target) ?? 0;
      offset.set(0, Math.max(24, actorSpan * 1.75), 8);
      caption = `${actors.previous.replace("robot_", "peer ")} → ${actors.next.replace("robot_", "peer ")} / task handoff`;
      tracksSubject = true;
    } else {
      key = "reroute-detour";
      target.copy(robotObjects.get(actors.next)?.position ?? blocked);
      offset.set(-8, 17, 10);
      caption = `${actors.next.replace("robot_", "peer ")} / clear detour only`;
      tracksSubject = true;
    }
  }

  target.x += 4.5;
  const desiredPosition = target.clone().add(offset);
  if (key !== directorShotKey) {
    directorShotKey = key;
    directorShotElapsed = 0;
    directorFromPosition.copy(camera.position);
    directorFromTarget.copy(controls.target);
  }
  directorShotElapsed += delta;
  const blend = THREE.MathUtils.smoothstep(Math.min(directorShotElapsed / 1.15, 1), 0, 1);
  if (blend < 1) {
    camera.position.lerpVectors(directorFromPosition, desiredPosition, blend);
    controls.target.lerpVectors(directorFromTarget, target, blend);
  } else if (tracksSubject) {
    const damping = 1 - Math.exp(-delta * .85);
    camera.position.lerp(desiredPosition, damping);
    controls.target.lerp(target, damping);
  } else {
    camera.position.copy(desiredPosition);
    controls.target.copy(target);
  }
  camera.lookAt(controls.target);
  q("#shot-caption").textContent = caption;
}

function disposeRobotObject(root: THREE.Object3D) {
  root.traverse(child => {
    if (child instanceof THREE.Sprite) {
      child.material.map?.dispose();
      child.material.dispose();
      return;
    }
    if (!(child instanceof THREE.Mesh)) return;
    const transientGeometry = child.name === "soft contact shadow" || child.name === "selection ring" || child.name === "top identity beacon";
    if (transientGeometry) child.geometry.dispose();
    const materials = Array.isArray(child.material) ? child.material : [child.material];
    materials.forEach(material => {
      if (material.userData.kinesisClone || transientGeometry) material.dispose();
    });
  });
}

function clearRouteOverlays() {
  routes.traverse(child => {
    if (!(child instanceof THREE.Line)) return;
    child.geometry.dispose();
    const materials = Array.isArray(child.material) ? child.material : [child.material];
    materials.forEach(material => material.dispose());
  });
  routes.clear();
}

function clearTransientGroup(group: THREE.Group) {
  group.traverse(child => {
    if (child instanceof THREE.Mesh || child instanceof THREE.Line || child instanceof THREE.LineSegments) {
      if (!child.userData.sharedGeometry) child.geometry.dispose();
      const materials = Array.isArray(child.material) ? child.material : [child.material];
      materials.forEach(material => material.dispose());
    }
    if (child instanceof THREE.Sprite) {
      child.material.map?.dispose();
      child.material.dispose();
    }
  });
  group.clear();
}

function explanationText(text: string, color: string) {
  const surface = document.createElement("canvas");
  surface.width = 1024;
  surface.height = 128;
  const context = surface.getContext("2d")!;
  context.clearRect(0, 0, surface.width, surface.height);
  context.shadowColor = "#000000";
  context.shadowBlur = 10;
  context.fillStyle = color;
  context.font = "700 35px ui-monospace, monospace";
  context.textAlign = "center";
  context.textBaseline = "middle";
  context.fillText(text, surface.width / 2, surface.height / 2);
  const texture = new THREE.CanvasTexture(surface);
  texture.colorSpace = THREE.SRGBColorSpace;
  const sprite = new THREE.Sprite(new THREE.SpriteMaterial({ map: texture, transparent: true, depthWrite: false, depthTest: false, toneMapped: false }));
  sprite.scale.set(8.6, 1.08, 1);
  sprite.renderOrder = 12;
  return sprite;
}

function buildExplanationOverlay() {
  clearTransientGroup(explanationOverlay);
  explanationLabel = null;
  broadcastRings.length = 0;
  causalBaseLines.length = 0;
  causalGlowLines.length = 0;
  causalLines.length = 0;
  scenario.robots.forEach((robot, index) => {
    const ring = new THREE.Mesh(
      new THREE.RingGeometry(.7, .86, 40),
      new THREE.MeshBasicMaterial({ color: 0x78e5ff, transparent: true, opacity: .5, side: THREE.DoubleSide, depthWrite: false, depthTest: false }),
    );
    ring.name = "broadcast wave";
    ring.rotation.x = -Math.PI / 2;
    ring.userData.robotId = robot.id;
    ring.userData.phase = index / scenario.robots.length;
    ring.renderOrder = 10;
    broadcastRings.push(ring);
    explanationOverlay.add(ring);
  });
  explanationRing = new THREE.Mesh(
    new THREE.RingGeometry(1.55, 1.82, 56),
    new THREE.MeshBasicMaterial({ color: 0x78e5ff, transparent: true, opacity: .82, side: THREE.DoubleSide, depthWrite: false, depthTest: false }),
  );
  explanationRing.name = "explanation focus";
  explanationRing.rotation.x = -Math.PI / 2;
  explanationRing.renderOrder = 10;
  explanationOverlay.add(explanationRing);
  for (let index = 0; index < 5; index++) {
    const createLine = (linewidth: number, opacity: number, renderOrder: number) => {
      const material = new LineMaterial({ color: 0x9cecff, linewidth, transparent: true, opacity, depthWrite: false, depthTest: false, toneMapped: false });
      material.resolution.set(innerWidth, innerHeight);
      const geometry = new LineGeometry();
      geometry.setPositions([0, 0, 0, 0, 0, 0]);
      const line = new Line2(geometry, material);
      line.frustumCulled = false;
      line.visible = false;
      line.renderOrder = renderOrder;
      explanationOverlay.add(line);
      return line;
    };
    causalBaseLines.push(createLine(2.2, .78, 10));
    causalGlowLines.push(createLine(9, .16, 11));
    causalLines.push(createLine(3.8, .98, 12));
  }
  explanationKey = "";
}

function showRobotRing(id: string, color: number, progress: number, hold = false) {
  const ring = broadcastRings.find(item => item.userData.robotId === id);
  const robot = robotObjects.get(id);
  if (!ring || !robot) return;
  const amount = THREE.MathUtils.clamp(progress, 0, 1);
  ring.visible = true;
  ring.position.set(robot.position.x, .11, robot.position.z);
  ring.scale.setScalar(hold ? 1.18 : .72 + amount * 2.05);
  const material = ring.material as THREE.MeshBasicMaterial;
  material.color.setHex(color);
  material.opacity = hold ? .72 : (1 - amount) * .78;
}

function focusExplanation(position: THREE.Vector3, color: number, progress: number, expand = false) {
  if (!explanationRing) return;
  explanationRing.visible = true;
  explanationRing.position.set(position.x, .105, position.z);
  const amount = THREE.MathUtils.clamp(progress, 0, 1);
  explanationRing.scale.setScalar(expand ? .75 + amount * 1.8 : .96 + amount * .14);
  const material = explanationRing.material as THREE.MeshBasicMaterial;
  material.color.setHex(color);
  material.opacity = expand ? (1 - amount) * .72 : .76;
}

function causalCurve(from: THREE.Vector3, to: THREE.Vector3, bend = .11) {
  const direction = new THREE.Vector2(to.x - from.x, to.z - from.z);
  const distance = direction.length();
  const heading = direction.clone().normalize();
  const inset = Math.min(.78, distance * .16);
  const start = new THREE.Vector3(from.x + heading.x * inset, 1.08, from.z + heading.y * inset);
  const end = new THREE.Vector3(to.x - heading.x * inset, 1.08, to.z - heading.y * inset);
  const span = new THREE.Vector2(end.x - start.x, end.z - start.z);
  const lateral = new THREE.Vector2(-span.y, span.x).normalize().multiplyScalar(Math.min(span.length() * bend, 1.5));
  const control = new THREE.Vector3((start.x + end.x) / 2 + lateral.x, 1.7, (start.z + end.z) / 2 + lateral.y);
  return Array.from({ length: 25 }, (_, index) => {
    const phase = index / 24;
    const inverse = 1 - phase;
    return start.clone().multiplyScalar(inverse * inverse)
      .addScaledVector(control, 2 * inverse * phase)
      .addScaledVector(end, phase * phase);
  });
}

function pathPoint(points: THREE.Vector3[], progress: number) {
  const scaled = THREE.MathUtils.clamp(progress, 0, 1) * (points.length - 1);
  const index = Math.floor(scaled);
  return points[index].clone().lerp(points[Math.min(index + 1, points.length - 1)], scaled - index);
}

function pathSegment(points: THREE.Vector3[], startProgress: number, endProgress: number) {
  const start = THREE.MathUtils.clamp(startProgress, 0, 1);
  const end = THREE.MathUtils.clamp(endProgress, start, 1);
  const startIndex = Math.floor(start * (points.length - 1));
  const endIndex = Math.floor(end * (points.length - 1));
  const segment = [pathPoint(points, start)];
  for (let index = startIndex + 1; index <= endIndex; index++) segment.push(points[index].clone());
  segment.push(pathPoint(points, end));
  if (segment.length < 2) segment.push(segment[0].clone());
  return segment;
}

function showCausalPath(index: number, points: THREE.Vector3[], color: number, drawProgress = 1, messageProgress: number | null = null) {
  const base = causalBaseLines[index];
  const glow = causalGlowLines[index];
  const line = causalLines[index];
  if (!base || !glow || !line || points.length < 2 || !linksEnabled) return;
  const strokeProgress = Math.min(
    THREE.MathUtils.clamp(drawProgress, 0, 1),
    messageProgress === null ? 1 : THREE.MathUtils.clamp(messageProgress, 0, 1),
  );
  const activePoints = pathSegment(points, Math.max(0, strokeProgress - .2), strokeProgress);
  const fullPositions = points.flatMap(point => [point.x, point.y, point.z]);
  const tracerPositions = activePoints.flatMap(point => [point.x, point.y, point.z]);
  base.geometry.setPositions(fullPositions);
  glow.geometry.setPositions(tracerPositions);
  line.geometry.setPositions(tracerPositions);
  for (const layer of [base, glow, line]) {
    layer.material.color.setHex(color);
    layer.material.resolution.set(innerWidth, innerHeight);
  }
  base.visible = true;
  glow.visible = strokeProgress > .01;
  line.visible = strokeProgress > .01;
}

function nearestRobotIds(id: string, count: number, excluded: string[] = []) {
  const origin = robotObjects.get(id)?.position;
  if (!origin) return [];
  return [...robotObjects.entries()]
    .filter(([candidate]) => candidate !== id && !excluded.includes(candidate))
    .sort((a, b) => origin.distanceToSquared(a[1].position) - origin.distanceToSquared(b[1].position))
    .slice(0, count)
    .map(([candidate]) => candidate);
}

function stableNearestRobotIds(id: string, count: number, tick: number, excluded: string[] = []) {
  const epoch = Math.floor(tick / 6);
  const key = `${scenario.id}:${epoch}:${id}:${count}:${[...excluded].sort().join(",")}`;
  const cached = peerNeighborCache.get(key);
  if (cached) return cached;
  if (peerNeighborCache.size > 96) peerNeighborCache.clear();
  const nearest = nearestRobotIds(id, count, excluded);
  peerNeighborCache.set(key, nearest);
  return nearest;
}

/** The reservation rejections the simulator actually recorded, in tick order. */
type StoryBeat = { from: number; step: string; title: string; copy: string; label: string; color: string };
let storyCache: { id: string; beats: StoryBeat[] } | null = null;

function firstTick(kind: string, fallback: number) {
  return scenario.events.find(event => event.kind === kind)?.tick ?? fallback;
}

function lastTick(kind: string, fallback: number) {
  return [...scenario.events].reverse().find(event => event.kind === kind)?.tick ?? fallback;
}

/**
 * Each case as three acts plus a result, anchored to the ticks its own events
 * actually happen at. Written so a viewer who knows nothing can follow: what
 * the situation is, what goes wrong, what the fleet does, and how it ended.
 */
function buildStoryBeats(): StoryBeat[] {
  const orders = new Set(scenario.events.filter(e => e.kind === "task_announced").map(e => e.entityId)).size;
  const done = lastTick("task_completed", scenario.duration);

  if (scenario.id === "conflict-resolution") {
    const clash = scenario.events.find(event => event.kind === "plan_conflict_rejected");
    const at = Number(clash?.data.conflict_tick ?? clash?.tick ?? 0);
    const refused = robotName(String(clash?.data.robot_id ?? ""));
    const holder = robotName(String(clash?.data.owner_id ?? ""));
    return [
      { from: 0, step: "ACT 1 / THE SQUEEZE", title: `${orders} PEERS, ONE SINGLE-CELL GAP`,
        copy: "Every route here must pass through one gap in the rack row. It fits exactly one robot at a time, and two peers want it on the same tick.",
        label: "ONE CELL WIDE", color: "#9cecff" },
      { from: Math.max(1, at), step: "ACT 2 / THE REFUSAL", title: `${refused.toUpperCase()} IS REFUSED THE CELL`,
        copy: `${holder} already reserved that cell for that exact tick, so the overlapping plan is rejected before either robot moves. Nothing has to brake.`,
        label: "PLAN REJECTED", color: "#ffcf63" },
      { from: at + 6, step: "ACT 3 / THE DETOUR", title: `${refused.toUpperCase()} RE-PLANS AND GOES ROUND`,
        copy: "The refused peer takes the next free gap instead of queueing. The reservation, not a traffic rule, is what keeps them apart.",
        label: "REROUTED", color: "#8fffc6" },
      { from: done, step: "RESULT", title: `ALL ${orders} ORDERS DELIVERED, ZERO COLLISIONS`,
        copy: "One plan refused, one detour taken, every order still landed inside the shift.",
        label: `${orders} / ${orders} DELIVERED`, color: "#8fffc6" },
    ];
  }

  if (scenario.id === "task-rerouting") {
    const at = scenario.incidents[0]?.tick ?? firstTick("cells_blocked", 14);
    const requeued = scenario.events.filter(event => event.kind === "task_requeued").length;
    return [
      { from: 0, step: "ACT 1 / NORMAL RUN", title: `${orders} ORDERS ROUTED THROUGH ONE GAP`,
        copy: "The fleet is working normally. Every live route depends on the same gap through the rack row.",
        label: "ROUTES COMMITTED", color: "#9cecff" },
      { from: at, step: "ACT 2 / THE BLOCK", title: "THE GAP CLOSES WHILE ROBOTS ARE COMMITTED",
        copy: `That cell becomes impassable mid-route. ${requeued} live assignments are invalidated on the spot — including one robot already carrying a payload.`,
        label: "AISLE BLOCKED", color: "#ff7e6b" },
      { from: at + 2, step: "ACT 3 / BACK TO AUCTION", title: "THE LOST WORK IS RE-AUCTIONED",
        copy: "No supervisor reassigns anything. The freed orders go back out to the peers, who re-bid and re-plan around the closed cell.",
        label: `${requeued} REASSIGNED`, color: "#ffe093" },
      { from: done, step: "RESULT", title: `ALL ${orders} ORDERS STILL DELIVERED`,
        copy: "The block cost a detour, not a delivery. Nothing was dropped and nothing collided.",
        label: `${orders} / ${orders} DELIVERED`, color: "#8fffc6" },
    ];
  }

  const award = firstTick("task_awarded", 0);
  const pick = firstTick("task_picked", 6);
  return [
    { from: 0, step: "ACT 1 / THE ORDER", title: `${orders} ORDERS ARRIVE, NOBODY IS IN CHARGE`,
      copy: "There is no dispatcher and no server. Each order is announced to every peer, and every peer prices it from where it happens to be standing.",
      label: "NO CENTRAL SERVER", color: "#9cecff" },
    { from: Math.max(1, award), step: "ACT 2 / THE AUCTION", title: "THE CHEAPEST BID WINS THE ORDER",
      copy: "A bid is that robot's own cost: distance to the pickup, battery left, and work already queued. Lowest bid takes the job — no vote, no coordinator.",
      label: "CHEAPEST PEER WINS", color: "#ffe093" },
    { from: Math.max(2, pick), step: "ACT 3 / THE DELIVERY", title: "THE WINNER CARRIES ITS OWN ORDER",
      copy: "The peer that won is the peer that drives. It reserves the cells it needs, collects the payload and delivers without asking anyone.",
      label: "SELF-DIRECTED", color: "#8fffc6" },
    { from: done, step: "RESULT", title: `ALL ${orders} ORDERS DELIVERED`,
      copy: "Every order announced in this run was bid for, won and delivered inside the shift.",
      label: `${orders} / ${orders} DELIVERED`, color: "#8fffc6" },
  ];
}

function storyBeats() {
  if (storyCache?.id !== scenario.id) storyCache = { id: scenario.id, beats: buildStoryBeats() };
  return storyCache.beats;
}

/** Show the act that is running at `tick`, anchored at `position`. */
function applyStoryBeat(tick: number, position: THREE.Vector3) {
  const beats = storyBeats();
  let active = beats[0];
  for (const beat of beats) if (tick >= beat.from) active = beat;
  setExplanation(`${scenario.id}-${active.step}`, active.step, active.title, active.copy, active.label, active.color, position);
}

const leadPeerCache = new Map<string, string>();
const NOTEWORTHY = new Set(["task_picked", "task_dropped", "task_completed", "zone_lease_entered", "plan_conflict_rejected"]);

function isMovingNear(trace: RobotTrace, tick: number) {
  const frames = trace.frames;
  const from = Math.max(1, Math.floor(tick) - 4);
  const to = Math.min(frames.length - 1, Math.floor(tick) + 12);
  for (let index = from; index <= to; index++) {
    if (Math.abs(frames[index].x - frames[index - 1].x) > 1e-6) return true;
    if (Math.abs(frames[index].z - frames[index - 1].z) > 1e-6) return true;
  }
  return false;
}

/**
 * The peer worth watching at `tick`: one that is actually driving, preferring
 * whoever reaches a pickup/drop/reservation soonest.
 *
 * The previous rule — winner of the *first* award — pinned every shot to one
 * robot for the whole run. In peer-network that is robot_09, which wins an
 * order whose pickup_tick (157) falls beyond the 150-tick horizon, so it parks
 * at tick 95 and the camera then watches it sit still for the last 44 seconds.
 * Held stable in 9-tick buckets so the framing does not jitter.
 */
function leadPeerAt(tick: number) {
  const key = `${scenario.id}:${Math.floor(tick / 9)}`;
  const cached = leadPeerCache.get(key);
  if (cached) return cached;
  if (leadPeerCache.size > 128) leadPeerCache.clear();
  const now = Math.max(0, Math.floor(tick));
  const moving = scenario.robots.filter(trace => isMovingNear(trace, now));
  const pool = moving.length ? moving : scenario.robots;
  let best = pool[0]?.id ?? "robot_09";
  let bestGap = Infinity;
  for (const event of scenario.events) {
    if (event.tick < now || !NOTEWORTHY.has(event.kind)) continue;
    const id = String(event.data.robot_id ?? "");
    if (!pool.some(trace => trace.id === id)) continue;
    if (event.tick - now < bestGap) { bestGap = event.tick - now; best = id; }
  }
  leadPeerCache.set(key, best);
  return best;
}

function conflictEvents() {
  return scenario.events
    .filter(event => event.kind === "plan_conflict_rejected")
    .sort((a, b) => a.tick - b.tick);
}

/**
 * The rejection nearest `tick`. `ownerId` already holds the reservation and
 * keeps moving; `rejectedId` is the peer whose candidate plan was refused and
 * which must re-plan. Both ids come from the event, never from proximity.
 */
function conflictBeatAt(tick: number) {
  const conflicts = conflictEvents();
  const imminent = conflicts.find(event => event.tick >= tick && event.tick - tick <= 8);
  const previous = [...conflicts].reverse().find(event => event.tick <= tick);
  const event = previous && tick - previous.tick <= 11 ? previous : imminent ?? previous ?? conflicts[0];
  if (!event) return { key: "fallback", tick: activeConflictTick, point: activeConflictPoint.clone(), winnerId: "robot_09", rejectedId: "robot_09" };
  const winnerId = String(event.data.owner_id ?? event.data.robot_id ?? "robot_09");
  const rejectedId = String(event.data.robot_id ?? winnerId);
  const world = event.data.world as { x: number; z: number } | undefined;
  const point = world
    ? new THREE.Vector3(world.x, .2, world.z)
    : activeConflictPoint.clone();
  return { key: `${event.entityId}-${event.tick}`, tick: Number(event.data.conflict_tick ?? event.tick), point, winnerId, rejectedId };
}

/** The two peers the recorded conflict actually names, owner first. */
function importantConflictIds(eventTick = activeConflictTick, point = activeConflictPoint) {
  const beat = conflictBeatAt(eventTick);
  const ids = [beat.winnerId, beat.rejectedId].filter(
    (id, index, all) => id && all.indexOf(id) === index && scenario.robots.some(robot => robot.id === id),
  );
  if (ids.length === 2) return ids;
  // Only reached for a trace with no recorded rejection at all.
  return scenario.robots
    .map(trace => ({ id: trace.id, frame: trace.frames[Math.min(eventTick, trace.frames.length - 1)] }))
    .sort((a, b) => Math.hypot(a.frame.x - point.x, a.frame.z - point.z) - Math.hypot(b.frame.x - point.x, b.frame.z - point.z))
    .slice(0, 2)
    .map(item => item.id);
}

function setExplanation(key: string, step: string, title: string, copy: string, label: string, color: string, position: THREE.Vector3) {
  if (key !== explanationKey) {
    explanationKey = key;
    q("#guide-step").textContent = step;
    q("#guide-title").textContent = title;
    q("#guide-copy").textContent = copy;
    const guide = q("#guide");
    guide.classList.remove("changing");
    void guide.offsetWidth;
    guide.classList.add("changing");
    if (explanationLabel) {
      explanationLabel.material.map?.dispose();
      explanationLabel.material.dispose();
      explanationOverlay.remove(explanationLabel);
    }
    explanationLabel = explanationText(label, color);
    explanationOverlay.add(explanationLabel);
  }
  explanationLabel?.position.set(position.x, 2.8, position.z);
}

function updateExplanation(tick: number, _time: number) {
  broadcastRings.forEach(ring => ring.visible = false);
  causalBaseLines.forEach(line => line.visible = false);
  causalGlowLines.forEach(line => line.visible = false);
  causalLines.forEach(line => line.visible = false);
  if (explanationRing) explanationRing.visible = false;

  if (scenario.id === "peer-network") {
    const phase = Math.floor(tick / 18) % 3;
    const phaseTick = tick % 18;
    const cycle = (phaseTick % 6) / 6;
    const senderId = leadPeerAt(tick);
    const sender = robotObjects.get(senderId)?.position ?? new THREE.Vector3(27, 0, -20);
    const recipients = stableNearestRobotIds(senderId, 3, tick);
    if (phase === 0) {
      if (cycle < .28) showRobotRing(senderId, 0x78e5ff, cycle / .28);
      recipients.forEach((id, index) => {
        const recipient = robotObjects.get(id)?.position;
        if (!recipient) return;
        const travel = THREE.MathUtils.clamp((cycle - .12 - index * .045) / .58, 0, 1);
        showCausalPath(index, causalCurve(sender, recipient), 0x78e5ff, travel, travel);
        if (travel > .82) showRobotRing(id, 0xf4fcff, (travel - .82) / .18);
      });
      applyStoryBeat(tick, sender);
    } else if (phase === 1) {
      const relayId = recipients[0] ?? senderId;
      const relay = robotObjects.get(relayId)?.position ?? sender;
      const nextHops = stableNearestRobotIds(relayId, 2, tick, [senderId]);
      const firstLeg = THREE.MathUtils.clamp(cycle / .48, 0, 1);
      showCausalPath(0, causalCurve(sender, relay), 0xf4fcff, firstLeg, firstLeg);
      if (cycle > .45) showRobotRing(relayId, 0xf4fcff, Math.min((cycle - .45) / .22, 1));
      nextHops.forEach((id, index) => {
        const destination = robotObjects.get(id)?.position;
        if (!destination) return;
        const secondLeg = THREE.MathUtils.clamp((cycle - .48 - index * .04) / .46, 0, 1);
        showCausalPath(index + 1, causalCurve(relay, destination), 0x78e5ff, secondLeg, secondLeg);
        if (secondLeg > .82) showRobotRing(id, 0x78e5ff, (secondLeg - .82) / .18);
      });
      applyStoryBeat(tick, relay);
    } else {
      showRobotRing(senderId, 0x64efb0, 0, true);
      focusExplanation(sender, 0x64efb0, 0);
      applyStoryBeat(tick, sender);
    }
    return;
  }

  if (scenario.id === "conflict-resolution") {
    if (compareMode === "without") {
      const converge = THREE.MathUtils.clamp(comparisonSeconds / 4.8, 0, 1);
      focusExplanation(activeConflictPoint, 0xff5d55, 1 - converge, true);
      // Not an invented scenario: the simulator recorded a rejected plan for
      // this exact cell and tick. This replays the route it refused to commit.
      setExplanation(
        comparisonSeconds < 4.8 ? "conflict-converge" : "conflict-hit",
        comparisonSeconds < 4.8 ? "01 / THE REJECTED PLAN" : "02 / WHY IT WAS REJECTED",
        comparisonSeconds < 4.8 ? "REPLAY OF THE PLAN THAT WAS REFUSED" : "BOTH REACH THIS CELL ON THE SAME TICK",
        comparisonSeconds < 4.8
          ? `Reconstructed from the recorded rejection at tick ${activeConflictTick}; no robot ever drove this route.`
          : "The reservation check caught this before either plan was committed.",
        comparisonSeconds < 4.8 ? "REJECTED PLAN · NOT EXECUTED" : "SAME CELL · SAME TICK",
        "#ff746d",
        activeConflictPoint,
      );
      return;
    }
    const beat = conflictBeatAt(tick);
    const actors = importantConflictIds(beat.tick, beat.point);
    const relativeTick = tick - beat.tick;
    const crossingProgress = THREE.MathUtils.clamp((relativeTick + 7) / 11, 0, 1);
    if (relativeTick >= -8 && relativeTick <= 11) {
      actors.forEach((id, index) => {
        const robot = robotObjects.get(id);
        if (!robot) return;
        const path = causalCurve(robot.position, beat.point, index === 0 ? .08 : -.08);
        if (id === beat.winnerId) {
          showCausalPath(index, path, 0x64efb0, 1, crossingProgress);
          showRobotRing(id, 0x64efb0, 0, true);
        } else {
          showCausalPath(index, path.slice(0, 18), 0xffcf63, 1, null);
          showRobotRing(id, 0xffcf63, 0, true);
        }
      });
    } else {
      showRobotRing(beat.winnerId, 0x64efb0, 0, true);
    }
    focusExplanation(beat.point, relativeTick < 4 ? 0xffcf63 : 0x64efb0, 0);
    if (relativeTick < -2) {
      applyStoryBeat(tick, beat.point);
    } else if (relativeTick < 4) {
      applyStoryBeat(tick, beat.point);
    } else {
      applyStoryBeat(tick, beat.point);
    }
    return;
  }

  const incident = scenario.incidents[0];
  const incidentTick = incident?.tick ?? 35;
  const blocked = incident ? new THREE.Vector3(-15 + incident.cell[0] * 1.5, 0, -(-9 + incident.cell[1] * 1.5)) : new THREE.Vector3(27, 0, -20);
  const actors = rerouteActors();
  const previous = robotObjects.get(actors.previous)?.position ?? blocked;
  const next = robotObjects.get(actors.next)?.position ?? blocked;
  if (tick < incidentTick) {
    const scan = (tick % 5) / 5;
    focusExplanation(blocked, 0xffcf63, scan, true);
    applyStoryBeat(tick, blocked);
  } else if (tick < incidentTick + 5) {
    const stop = THREE.MathUtils.clamp((tick - incidentTick) / 5, 0, 1);
    showCausalPath(0, causalCurve(previous, blocked, .04), 0xff654f, 1, Math.min(stop, .82));
    focusExplanation(blocked, 0xff654f, 0);
    showRobotRing(actors.previous, 0xff654f, 0, true);
    applyStoryBeat(tick, blocked);
  } else if (tick < incidentTick + 16) {
    const handoff = THREE.MathUtils.clamp((tick - incidentTick - 5) / 11, 0, 1);
    showCausalPath(0, causalCurve(previous, next, .15), 0x78e5ff, handoff, handoff);
    showRobotRing(actors.previous, 0xffcf63, 0, true);
    if (handoff > .72) showRobotRing(actors.next, 0x78e5ff, (handoff - .72) / .28);
    const midpoint = previous.clone().lerp(next, .5);
    applyStoryBeat(tick, midpoint);
  } else {
    const trace = scenario.robots.find(robot => robot.id === actors.next);
    const start = Math.min(Math.floor(tick), (trace?.frames.length ?? 1) - 1);
    const path = trace?.frames.slice(start, start + 20).map(frame => new THREE.Vector3(frame.x, 1.05, frame.z)) ?? [];
    if (path.length > 1) showCausalPath(0, path, 0x64efb0, 1, ((tick - incidentTick - 16) % 8) / 8);
    showRobotRing(actors.next, 0x64efb0, 0, true);
    applyStoryBeat(tick, next);
  }
}

function buildPeerOverlay() {
  clearTransientGroup(peerOverlay);
  peerLines.length = 0;
  peerGlowLines.length = 0;
  for (let index = 0; index < 24; index++) {
    const linkMaterial = new LineMaterial({ color: 0xa8edff, linewidth: 1.9, transparent: true, opacity: .72, depthWrite: false, depthTest: false, toneMapped: false });
    linkMaterial.resolution.set(innerWidth, innerHeight);
    const linkGeometry = new LineGeometry();
    linkGeometry.setPositions([0, 0, 0, 0, 0, 0]);
    const link = new Line2(linkGeometry, linkMaterial);
    link.frustumCulled = false;
    link.renderOrder = 7;
    peerLines.push(link);
    peerOverlay.add(link);

    const glowMaterial = new LineMaterial({ color: 0x55d7ff, linewidth: 7.5, transparent: true, opacity: .14, depthWrite: false, depthTest: false, toneMapped: false });
    glowMaterial.resolution.set(innerWidth, innerHeight);
    const glowGeometry = new LineGeometry();
    glowGeometry.setPositions([0, 0, 0, 0, 0, 0]);
    const glow = new Line2(glowGeometry, glowMaterial);
    glow.frustumCulled = false;
    glow.renderOrder = 6;
    peerGlowLines.push(glow);
    peerOverlay.add(glow);
  }

}

function peerEdges(tick: number) {
  const ids = scenario.robots.map(robot => robot.id);
  const unique = new Map<string, [string, string]>();
  for (const id of ids) {
    const origin = robotObjects.get(id)?.position;
    if (!origin) continue;
    const nearest = stableNearestRobotIds(id, 2, tick);
    for (const other of nearest) {
      const pair = [id, other].sort() as [string, string];
      unique.set(pair.join("/"), pair);
    }
  }
  return [...unique.values()];
}

function peerArc(from: THREE.Vector3, to: THREE.Vector3, phase: number) {
  const direction = new THREE.Vector2(to.x - from.x, to.z - from.z);
  const distance = direction.length();
  const heading = direction.clone().normalize();
  const inset = Math.min(.68, distance * .14);
  const start = new THREE.Vector3(from.x + heading.x * inset, 1.18, from.z + heading.y * inset);
  const end = new THREE.Vector3(to.x - heading.x * inset, 1.18, to.z - heading.y * inset);
  const height = 1.4 + Math.min(distance * .05, 1.1);
  const control = new THREE.Vector3((start.x + end.x) / 2, height, (start.z + end.z) / 2);
  const lateral = new THREE.Vector2(-(end.z - start.z), end.x - start.x).normalize()
    .multiplyScalar(Math.min(distance * .07, 1.25));
  control.x += lateral.x;
  control.z += lateral.y;
  const inverse = 1 - phase;
  return start.multiplyScalar(inverse * inverse)
    .addScaledVector(control, 2 * inverse * phase)
    .addScaledVector(end, phase * phase);
}

function updatePeerOverlay(_time: number) {
  if (!scenario) return;
  const show = scenario.id === "peer-network";
  peerOverlay.visible = show && linksEnabled;
  const tick = elapsedSeconds / scenario.tickSeconds;
  const peerLead = leadPeerAt(tick);
  const importantLabels = scenario.id === "peer-network"
    ? [peerLead, ...stableNearestRobotIds(peerLead, 3, tick)]
    : scenario.id === "conflict-resolution"
      ? (() => { const beat = conflictBeatAt(elapsedSeconds / scenario.tickSeconds); return importantConflictIds(beat.tick, beat.point); })()
      : Object.values(rerouteActors());
  robotObjects.forEach(object => {
    const tag = object.getObjectByName("peer identity tag");
    if (tag) tag.visible = importantLabels.includes(object.userData.robotId) || (cameraMode === "follow" && object.userData.robotId === selectedId);
  });
  if (!show || !linksEnabled) return;
  const edges = peerEdges(tick);
  peerLines.forEach((line, index) => {
    const glow = peerGlowLines[index];
    const edge = edges[index];
    line.visible = Boolean(edge);
    glow.visible = Boolean(edge);
    if (!edge) return;
    const [fromId, toId] = edge;
    const from = robotObjects.get(fromId)?.position ?? new THREE.Vector3();
    const to = robotObjects.get(toId)?.position ?? new THREE.Vector3();
    const positions: number[] = [];
    for (let point = 0; point <= 16; point++) {
      const position = peerArc(from, to, point / 16);
      positions.push(position.x, position.y, position.z);
    }
    line.geometry.setPositions(positions);
    glow.geometry.setPositions(positions);
    line.material.resolution.set(innerWidth, innerHeight);
    glow.material.resolution.set(innerWidth, innerHeight);
  });
}

function conflictPointFromTrace() {
  const conflict = scenario.events?.find(event => event.kind === "plan_conflict_rejected");
  const lease = scenario.events?.find(event => event.kind === "zone_lease_entered");
  activeConflictTick = Number(conflict?.data.conflict_tick ?? conflict?.tick ?? lease?.tick ?? 22);
  const world = conflict?.data.world as { x: number; z: number } | undefined;
  const edge = conflict?.data.worldEdge as { x: number; z: number }[] | undefined;
  if (world) activeConflictPoint.set(world.x, .2, world.z);
  else if (edge?.length) {
    activeConflictPoint.set(
      edge.reduce((sum, item) => sum + item.x, 0) / edge.length,
      .2,
      edge.reduce((sum, item) => sum + item.z, 0) / edge.length,
    );
  } else {
    const leaseRobot = scenario.robots.find(robot => robot.id === String(lease?.data.robot_id ?? ""));
    const leaseFrame = leaseRobot?.frames[Math.min(activeConflictTick, (leaseRobot?.frames.length ?? 1) - 1)];
    if (leaseFrame) activeConflictPoint.set(leaseFrame.x, .2, leaseFrame.z);
    else activeConflictPoint.set(27, .2, -20);
  }
}

function addConflictMarker() {
  const marker = new THREE.Group();
  marker.name = "conflict marker";
  const ring = new THREE.Mesh(
    new THREE.RingGeometry(2.3, 2.55, 48),
    new THREE.MeshBasicMaterial({ color: 0xff5d55, transparent: true, opacity: .95, side: THREE.DoubleSide, depthWrite: false }),
  );
  ring.rotation.x = -Math.PI / 2; ring.position.y = .08; ring.name = "conflict pulse"; marker.add(ring);
  const xMaterial = new THREE.MeshBasicMaterial({ color: 0xff5d55, transparent: true, opacity: .9, depthWrite: false });
  for (const rotation of [Math.PI / 4, -Math.PI / 4]) {
    const bar = new THREE.Mesh(new THREE.BoxGeometry(3.2, .03, .16), xMaterial);
    bar.rotation.y = rotation; bar.position.y = .1; marker.add(bar);
  }
  marker.position.copy(activeConflictPoint);
  incidentOverlay.add(marker);
}

function buildComparisonOverlay() {
  clearTransientGroup(comparisonOverlay);
  const traces = scenario.robots.slice(0, 2);
  traces.forEach(trace => {
    const robot = makeRobotObject(trace);
    robot.name = `counterfactual ${trace.id}`;
    comparisonOverlay.add(robot);
  });
  const points = [
    activeConflictPoint.clone().add(new THREE.Vector3(-8, .12, 0)),
    activeConflictPoint.clone().add(new THREE.Vector3(8, .12, 0)),
  ];
  points.forEach(start => {
    const geometry = new THREE.BufferGeometry().setFromPoints([start, activeConflictPoint.clone().setY(.12)]);
    comparisonOverlay.add(new THREE.Line(geometry, new THREE.LineBasicMaterial({ color: 0xffd9d7, transparent: true, opacity: .75 })));
  });
}

function buildBlockers() {
  blockerMeshes.splice(0);
  const obstacleMaterial = new THREE.MeshStandardMaterial({ color: 0xff7a45, emissive: 0x7a210c, emissiveIntensity: .8, roughness: .42 });
  scenario.obstacles.forEach(obstacle => obstacle.cells.forEach(([cellX, cellY]) => {
    const group = new THREE.Group();
    const block = new THREE.Mesh(new THREE.BoxGeometry(1.25, 1.1, 1.25), obstacleMaterial.clone());
    block.position.y = .62; block.castShadow = true; group.add(block);
    const halo = new THREE.Mesh(new THREE.RingGeometry(1.1, 1.32, 36), new THREE.MeshBasicMaterial({ color: 0xff754f, transparent: true, opacity: .8, side: THREE.DoubleSide }));
    halo.rotation.x = -Math.PI / 2; halo.position.y = .06; halo.name = "blocker pulse"; group.add(halo);
    group.position.set(-15 + cellX * 1.5, 0, -(-9 + cellY * 1.5));
    group.userData.fromTick = obstacle.fromTick; group.userData.toTick = obstacle.toTick;
    blockerMeshes.push(group); incidentOverlay.add(group);
  }));
}

function updateScenarioOverlays(tick: number, time: number) {
  const conflictMarker = incidentOverlay.getObjectByName("conflict marker");
  if (conflictMarker) {
    conflictMarker.visible = scenario.id === "conflict-resolution" && compareMode === "without";
    const pulse = conflictMarker.getObjectByName("conflict pulse");
    if (pulse) pulse.scale.setScalar(1 + Math.sin(time * 5) * .1);
  }
  blockerMeshes.forEach(blocker => {
    blocker.visible = tick >= Number(blocker.userData.fromTick) && tick <= Number(blocker.userData.toTick);
    const pulse = blocker.getObjectByName("blocker pulse");
    if (pulse) pulse.scale.setScalar(1 + Math.sin(time * 4) * .12);
  });
  comparisonOverlay.visible = scenario.id === "conflict-resolution" && compareMode === "without";
  fleet.visible = !comparisonOverlay.visible;
  routes.visible = !comparisonOverlay.visible;
  if (!comparisonOverlay.visible) return;
  const seconds = comparisonSeconds;
  const alpha = THREE.MathUtils.smoothstep(seconds, .6, 4.8);
  const starts = [
    activeConflictPoint.clone().add(new THREE.Vector3(-8, .17, 0)),
    activeConflictPoint.clone().add(new THREE.Vector3(8, .17, 0)),
  ];
  comparisonOverlay.children.filter(child => child.name.startsWith("counterfactual")).forEach((robot, index) => {
    const collisionOffset = new THREE.Vector3(index === 0 ? -.32 : .32, 0, index === 0 ? .16 : -.16);
    robot.position.lerpVectors(starts[index], activeConflictPoint.clone().add(collisionOffset), alpha);
    // These two close along X, so they must face along X. Traces use
    // yaw = atan2(dz, dx) and updateWorld applies rotation.y = -yaw, giving
    // 0 for +X travel and -PI for -X. Facing +/-PI/2 made them strafe sideways.
    robot.rotation.y = index === 0 ? 0 : -Math.PI;
  });
  if (seconds > 8) setCompareMode("with");
}

function populateFleet() {
  robotObjects.forEach(disposeRobotObject);
  fleet.clear(); robotObjects.clear();
  scenario.robots.forEach(robot => {
    const object = makeRobotObject(robot);
    robotObjects.set(robot.id, object);
    fleet.add(object);
  });
  selectRobot(selectedId);
}

async function loadScenario(id: string) {
  const meta = manifest.scenarios.find(item => item.id === id) ?? manifest.scenarios[0];
  scenario = await fetch(meta.file).then(response => response.json()) as Scenario;
  scenario.events ??= [];
  peerNeighborCache.clear();
  leadPeerCache.clear();
  minimapBackdrop = null;
  elapsedSeconds = scenario.id === "task-rerouting" ? 24 * scenario.tickSeconds : 0;
  lastRouteTick = -99; hazard.visible=false; comparisonSeconds = 0; directorShotKey = "";
  populateFleet();
  buildPeerOverlay();
  buildExplanationOverlay();
  clearTransientGroup(incidentOverlay);
  conflictPointFromTrace();
  if (scenario.id === "conflict-resolution") {
    addConflictMarker();
    buildComparisonOverlay();
    compareMode = "without";
  } else {
    clearTransientGroup(comparisonOverlay);
    compareMode = "with";
  }
  buildBlockers();
  if(!introActive)setCameraMode("auto");
  renderCasePanel();
  updateWorld(elapsedSeconds / scenario.tickSeconds);
  updateRoutes(elapsedSeconds / scenario.tickSeconds);
  playing=true;
  syncPlayControl();
}

function renderCasePanel() {
  q("#compare-toggle").hidden = scenario.id !== "conflict-resolution";
  q("#links-toggle").hidden = scenario.id !== "peer-network";
  document.querySelectorAll<HTMLButtonElement>("[data-compare]").forEach(button => {
    button.classList.toggle("active", button.dataset.compare === compareMode);
  });
}

function setCompareMode(mode: "without" | "with") {
  compareMode = mode;
  comparisonSeconds = 0;
  directorShotKey = "";
  if (mode === "with") {
    elapsedSeconds = Math.max(0, activeConflictTick - 7) * scenario.tickSeconds;
    playing = true;
    updateWorld(elapsedSeconds / scenario.tickSeconds);
    updateRoutes(elapsedSeconds / scenario.tickSeconds);
  }
  renderCasePanel();
  syncPlayControl();
}

function robotName(id: string) {
  const trace = scenario.robots.find(robot => robot.id === id);
  return trace ? `${trace.name} ${id.slice(-2)}` : id.replace("robot_", "peer ");
}

function orderName(entityId: string) {
  return entityId.startsWith("fc_order_") ? `order ${entityId.slice(-3)}` : entityId;
}

/**
 * Plain-English line for one recorded event, or null for the high-frequency
 * bookkeeping kinds (robot_moved, task_bid) that would drown the log.
 */
function describeEvent(event: SimulationEvent): string | null {
  const who = robotName(String(event.data.robot_id ?? ""));
  const order = orderName(event.entityId);
  switch (event.kind) {
    case "task_announced": return `<b>${order}</b> released to the fleet`;
    case "task_awarded": return `<b>${who}</b> won ${order} — best bid of the round`;
    case "task_picked": return `<b>${who}</b> picked up ${order}`;
    case "task_dropped": return `<b>${who}</b> dropped ${order} at its bay`;
    case "task_completed": return `<b>${order}</b> complete`;
    case "zone_lease_entered": return `<b>${who}</b> reserved ${event.entityId}`;
    case "zone_lease_released": return `<b>${who}</b> released ${event.entityId}`;
    case "task_requeued": return `<b>${order}</b> route invalidated — back to auction`;
    case "cells_blocked": return `<b>Aisle blocked</b> — that cell is now off-limits`;
    case "plan_conflict_rejected":
      return `<b>${who}</b> refused a plan — cell already held by ${robotName(String(event.data.owner_id ?? ""))}`;
    default: return null;
  }
}

/** The last few things that happened at or before `tick`, newest first. */
function updateEventFeed(tick: number) {
  const list = q("#feed-list");
  const recent: string[] = [];
  for (let index = scenario.events.length - 1; index >= 0 && recent.length < 4; index--) {
    const event = scenario.events[index];
    if (event.tick > tick) continue;
    const text = describeEvent(event);
    if (!text) continue;
    const age = tick - event.tick;
    recent.push(
      `<li class="${age > 12 ? "dim" : ""}"><time>${formatTime(event.tick * scenario.tickSeconds)}</time><span>${text}</span></li>`,
    );
  }
  const markup = recent.join("");
  if (list.dataset.markup !== markup) {
    list.dataset.markup = markup;
    list.innerHTML = markup || `<li class="dim"><time>--:--</time><span>waiting for the first order…</span></li>`;
  }
}

// ---- Floor plan -----------------------------------------------------------
// World<->grid: the trace stores world x/z, the grid stores cells. Cell size
// and origin come from the same layout the 3D scene is built from.
const CELL_M = 1.5, ORIGIN_X = -15, ORIGIN_Z = -9;
const cellOfWorld = (x: number, z: number): [number, number] =>
  [(x - ORIGIN_X) / CELL_M, (-z - ORIGIN_Z) / CELL_M];

let minimapBackdrop: HTMLCanvasElement | null = null;

/** Rack footprints never move, so bake them once per scenario. */
function buildMinimapBackdrop() {
  const grid = scenario.grid;
  if (!grid) return null;
  const host = document.querySelector<HTMLCanvasElement>("#minimap-canvas");
  if (!host) return null;
  const canvas = document.createElement("canvas");
  canvas.width = host.width; canvas.height = host.height;
  const paint = canvas.getContext("2d");
  if (!paint) return null;
  const sx = canvas.width / grid.width, sy = canvas.height / grid.height;
  paint.fillStyle = "#141a1f";
  paint.fillRect(0, 0, canvas.width, canvas.height);
  paint.fillStyle = "#5a6472";
  // Bake at canvas resolution so the racks stay crisp when CSS scales it down.
  for (const [x, y] of grid.blocked) paint.fillRect(x * sx, y * sy, Math.ceil(sx), Math.ceil(sy));
  return canvas;
}

function updateMinimap(tick: number) {
  const canvas = document.querySelector<HTMLCanvasElement>("#minimap-canvas");
  const grid = scenario.grid;
  if (!canvas || !grid) return;
  const paint = canvas.getContext("2d");
  if (!paint) return;
  if (!minimapBackdrop) minimapBackdrop = buildMinimapBackdrop();
  const sx = canvas.width / grid.width, sy = canvas.height / grid.height;
  paint.clearRect(0, 0, canvas.width, canvas.height);
    if (minimapBackdrop) paint.drawImage(minimapBackdrop, 0, 0, canvas.width, canvas.height);

  // aisle grid lines, faint
  paint.strokeStyle = "rgba(255,255,255,.05)"; paint.lineWidth = Math.max(0.5, sx * 0.12);
  for (let x = 0; x <= grid.width; x += 8) { paint.beginPath(); paint.moveTo(x*sx, 0); paint.lineTo(x*sx, canvas.height); paint.stroke(); }
  for (let y = 0; y <= grid.height; y += 8) { paint.beginPath(); paint.moveTo(0, y*sy); paint.lineTo(canvas.width, y*sy); paint.stroke(); }

  // blocked cells that are live at this tick
  for (const obstacle of scenario.obstacles ?? []) {
    if (tick < obstacle.fromTick || tick > obstacle.toTick) continue;
    paint.fillStyle = "#ff6b52";
    for (const [x, y] of obstacle.cells) paint.fillRect(x*sx - 1, y*sy - 1, sx + 2, sy + 2);
  }

  const points = scenario.robots.map(trace => {
    const frame = trace.frames[Math.max(0, Math.min(Math.floor(tick), trace.frames.length - 1))];
    const [cx, cy] = cellOfWorld(frame.x, frame.z);
    return { id: trace.id, color: trace.color, x: cx * sx, y: cy * sy, moving: frame.status === "moving" };
  });

  // peer links: direct-to-peer range, drawn only between nearby robots
  if (linksEnabled) {
    const range = 14 * sx;
    paint.lineWidth = Math.max(1, sx * 0.35);
    for (let a = 0; a < points.length; a++) {
      for (let b = a + 1; b < points.length; b++) {
        const distance = Math.hypot(points[a].x - points[b].x, points[a].y - points[b].y);
        if (distance > range) continue;
        paint.strokeStyle = `rgba(79,210,255,${(0.72 * (1 - distance / range)).toFixed(3)})`;
        paint.beginPath(); paint.moveTo(points[a].x, points[a].y); paint.lineTo(points[b].x, points[b].y); paint.stroke();
      }
    }
  }

  const lead = leadPeerAt(tick);
  for (const point of points) {
    if (point.id === lead) {
      paint.strokeStyle = "#ffffff"; paint.lineWidth = Math.max(1, sx * 0.3);
      paint.beginPath(); paint.arc(point.x, point.y, sx * 1.7, 0, Math.PI * 2); paint.stroke();
    }
    paint.fillStyle = point.color;
    paint.beginPath(); paint.arc(point.x, point.y, sx * (point.moving ? 1.05 : 0.8), 0, Math.PI * 2); paint.fill();
  }
}

// ---- Telemetry ------------------------------------------------------------
const TICK_SIM_SECONDS = 5;   // one algorithm tick is five simulated seconds

function updateTelemetry(tick: number) {
  const now = Math.max(1, Math.min(Math.floor(tick), scenario.duration));
  let moving = 0, carried = 0, metres = 0, battery = 0, fastest = 0;
  const positions: [number, number][] = [];
  for (const trace of scenario.robots) {
    const frames = trace.frames;
    const here = frames[Math.min(now, frames.length - 1)];
    const before = frames[Math.min(now - 1, frames.length - 1)];
    const step = Math.hypot(here.x - before.x, here.z - before.z);
    if (step > 1e-6) moving++;
    if (here.load) carried++;
    metres += step;
    fastest = Math.max(fastest, step / TICK_SIM_SECONDS);
    battery += here.battery;
    positions.push([here.x, here.z]);
  }
  const count = scenario.robots.length || 1;
  let separation = Infinity;
  for (let a = 0; a < positions.length; a++)
    for (let b = a + 1; b < positions.length; b++)
      separation = Math.min(separation, Math.hypot(positions[a][0]-positions[b][0], positions[a][1]-positions[b][1]));
  const done = scenario.events.filter(e => e.kind === "task_completed" && e.tick <= now).length;
  const orders = new Set(scenario.events.filter(e => e.kind === "task_announced").map(e => e.entityId)).size || 1;
  const refusals = scenario.events.filter(e => e.kind === "plan_conflict_rejected" && e.tick <= now).length;
  const requeues = scenario.events.filter(e => e.kind === "task_requeued" && e.tick <= now).length;
  const epoch = scenario.events
    .filter(e => e.kind === "task_awarded" && e.tick <= now)
    .reduce((top, e) => Math.max(top, Number(e.data.auction_epoch ?? 0)), 0);

  const cells = [
    ["fleet velocity", `${(metres / count / TICK_SIM_SECONDS).toFixed(2)}<small> m/s</small>`],
    ["peak velocity", `${fastest.toFixed(2)}<small> m/s</small>`],
    ["min separation", `${(separation === Infinity ? 0 : separation).toFixed(1)}<small> m</small>`],
    ["in motion", `${moving}<small> / ${count}</small>`],
    ["payloads held", `${carried}`],
    ["auction epoch", `#${epoch}`],
  ].map(([k, v]) => `<div><dt>${k}</dt><dd>${v}</dd></div>`).join("");
  const grid = q("#tel-grid");
  if (grid.dataset.markup !== cells) { grid.dataset.markup = cells; grid.innerHTML = cells; }

  const bars = [
    ["throughput", done / orders, `${done}/${orders}`, "#64efb0"],
    ["utilisation", moving / count, `${Math.round(moving / count * 100)}%`, "#78e5ff"],
    ["charge", battery / count, `${Math.round(battery / count * 100)}%`, "#ffcf63"],
  ].map(([label, ratio, text, tone]) =>
    `<div><span>${label}</span><i><b style="width:${Math.round(Math.min(1, Number(ratio)) * 100)}%;background:${tone}"></b></i><span>${text}</span></div>`).join("");
  const barHost = q("#tel-bars");
  if (barHost.dataset.markup !== bars) { barHost.dataset.markup = bars; barHost.innerHTML = bars; }

  q("#tel-foot").textContent =
    `t=${now}/${scenario.duration} · sim ${(now * TICK_SIM_SECONDS / 60).toFixed(1)}min · ` +
    `${refusals} plan refusal${refusals === 1 ? "" : "s"} · ${requeues} requeued · 0 executed conflicts`;
}

function updateInterface(tick: number) {
  renderCasePanel();
  updateEventFeed(tick);
  updateMinimap(tick);
  updateTelemetry(tick);
}

function frameAt(trace: RobotTrace, tick: number): [Frame, Frame, number] {
  const low=Math.max(0,Math.min(trace.frames.length-1,Math.floor(tick)));
  const high=Math.min(trace.frames.length-1,low+1);
  return [trace.frames[low],trace.frames[high],tick-low];
}

function updateWorld(tick: number) {
  if(!scenario) return;
  scenario.robots.forEach(trace=>{
    const object=robotObjects.get(trace.id); if(!object)return;
    const [a,b,alpha]=frameAt(trace,tick);
    object.position.set(THREE.MathUtils.lerp(a.x,b.x,alpha),.17,THREE.MathUtils.lerp(a.z,b.z,alpha));
    const turn=Math.atan2(Math.sin(b.yaw-a.yaw),Math.cos(b.yaw-a.yaw));
    object.rotation.y=-(a.yaw+turn*alpha);
    animateWheels(object, trace, tick);
    const ring=object.getObjectByName("selection ring");if(ring)ring.visible=trace.id===selectedId;
  });
  if(Math.abs(tick-lastRouteTick)>2){updateRoutes(tick);lastRouteTick=tick}
  updateReplayState(tick); updateIncident(tick);
}

function updateRoutes(tick: number) {
  clearRouteOverlays();
  const start=Math.floor(tick);
  const lead = leadPeerAt(tick);
  const importantRoutes = scenario.id === "peer-network"
    ? [lead]
    : scenario.id === "conflict-resolution"
      ? (() => { const beat = conflictBeatAt(tick); return importantConflictIds(beat.tick, beat.point); })()
      : Object.values(rerouteActors());
  scenario.robots.forEach(trace=>{
    const points:THREE.Vector3[]=[];
    for(let i=start;i<Math.min(trace.frames.length,start+28);i++){
      const f=trace.frames[i]; const point=new THREE.Vector3(f.x,.24,f.z);
      if(!points.length||point.distanceToSquared(points[points.length-1])>.01)points.push(point);
    }
    if(points.length<2)return;
    const geometry=new THREE.BufferGeometry().setFromPoints(points);
    const selected = cameraMode !== "auto" && trace.id === selectedId;
    const line=new THREE.Line(geometry,new THREE.LineBasicMaterial({color:trace.color,transparent:true,opacity:selected?.95:importantRoutes.includes(trace.id)?.62:.08,depthWrite:false}));
    line.userData.robotId=trace.id;routes.add(line);
  });
}

function updateReplayState(tick:number){
  const seconds=tick*scenario.tickSeconds;
  const total=scenario.duration*scenario.tickSeconds;
  const progress=THREE.MathUtils.clamp(tick/scenario.duration,0,1);
  q("#elapsed").textContent=formatTime(seconds);
  q("#duration").textContent=formatTime(total);
  timeline.style.setProperty("--progress",`${progress*100}%`);
  timeline.setAttribute("aria-valuemax",String(total));
  timeline.setAttribute("aria-valuenow",String(Math.round(seconds)));
  timeline.setAttribute("aria-valuetext",`${formatTime(seconds)} of ${formatTime(total)}`);
}

function updateIncident(tick:number){
  const current=scenario.incidents.find(item=>tick>=item.tick&&tick<item.tick+14);
  if(!current){hazard.visible=false;return}
  const x=-15+current.cell[0]*1.5,z=-(-9+current.cell[1]*1.5);hazard.position.set(x,0,z);hazard.visible=true;
  const pulse=hazard.getObjectByName("pulse");if(pulse)pulse.scale.setScalar(1+Math.sin(performance.now()*.008)*.09);
}

function selectRobot(id:string){
  selectedId=id;
  robotObjects.forEach((object,robotId)=>{const ring=object.getObjectByName("selection ring");if(ring)ring.visible=robotId===id});
  if(scenario)updateRoutes(elapsedSeconds/scenario.tickSeconds);
}

function setRoofOpen(open: boolean) {
  const update = (root: THREE.Object3D | null) => root?.traverse(object => {
    if (!/roof|skylight|ceiling light/i.test(object.name)) return;
    if (object.userData.closedVisibility === undefined) object.userData.closedVisibility = object.visible;
    object.visible = open ? false : Boolean(object.userData.closedVisibility);
  });
  update(fallbackWarehouse);
  update(detailedWarehouse);
}

function setCameraMode(mode:string){
  cameraMode=mode;
  if(mode==="auto") directorShotKey="";
  controls.enabled=mode==="explore";
  birdControls.enabled=mode==="bird";
  setRoofOpen(mode !== "cinematic");
  q<HTMLSelectElement>("#camera-select").value = mode === "cinematic" ? "auto" : mode;
  document.querySelectorAll<HTMLButtonElement>("[data-camera]").forEach(button => button.classList.toggle("active", button.dataset.camera === mode));
  if(mode!=="cinematic") introActive=false;
  if(mode==="bird"){
    birdCamera.zoom=1;
    birdCamera.updateProjectionMatrix();
    birdCamera.position.set(27,92,-20);
    birdCamera.up.set(0,0,-1);
    birdControls.target.set(27,0,-20);
    birdCamera.lookAt(birdControls.target);
  }
  if(mode==="explore"){
    camera.position.set(77,34,42); controls.target.set(27,1,-20); camera.lookAt(controls.target);
  }
  if(mode==="follow") controls.enabled=false;
}

function updateCamera(delta: number){
  if(cameraMode==="auto"){updateDirector(delta);return}
  if(cameraMode==="follow"){
    const robot=robotObjects.get(selectedId);if(robot){
      // Follow remains a high three-quarter view: the robot and its reserved
      // route are legible, while the floor context stays visible.
      const offset=new THREE.Vector3(-5.5,6.7,-5.5).applyAxisAngle(new THREE.Vector3(0,1,0),robot.rotation.y);
      const nextPosition=robot.position.clone().add(offset);
      camera.position.lerp(nextPosition,.075);
      const nextTarget=robot.position.clone().add(new THREE.Vector3(0,.6,0));
      controls.target.lerp(nextTarget,.12);
      camera.lookAt(controls.target);
    }
  }else if(cameraMode==="cinematic"){
    const elapsed=(performance.now()-introStartedAt)/1000;
    const alpha=THREE.MathUtils.smoothstep(elapsed,0,5.8);
    const start=new THREE.Vector3(96,48,72);
    const end=new THREE.Vector3(64,28,30);
    camera.position.lerpVectors(start,end,alpha);
    const targetStart=new THREE.Vector3(21,2,-11);
    const targetEnd=new THREE.Vector3(27,0,-20);
    camera.lookAt(targetStart.lerp(targetEnd,alpha));
    if(introActive&&elapsed>=6){
      introActive=false;
      
      setCameraMode("auto");
    }
  }
}

function formatTime(seconds:number){const value=Math.max(0,Math.round(seconds));return `${String(Math.floor(value/60)).padStart(2,"0")}:${String(value%60).padStart(2,"0")}`}

function syncPlayControl(){
  playButton.textContent = playing ? "pause" : "play";
  playButton.setAttribute("aria-label", playing ? "Pause replay" : "Play replay");
}

function togglePlay(){
  const total=scenario.duration*scenario.tickSeconds;
  if(!playing&&elapsedSeconds>=total)elapsedSeconds=0;
  playing=!playing;
  updateWorld(elapsedSeconds/scenario.tickSeconds);
  syncPlayControl();
}

function seekToProgress(progress:number){
  const clamped=THREE.MathUtils.clamp(progress,0,1);
  elapsedSeconds=clamped*scenario.duration*scenario.tickSeconds;
  updateWorld(elapsedSeconds/scenario.tickSeconds);
}

function progressAt(clientX:number){
  const rect=timeline.getBoundingClientRect();
  return THREE.MathUtils.clamp((clientX-rect.left)/Math.max(rect.width,1),0,1);
}

function previewAt(progress:number){
  const current=elapsedSeconds/(scenario.duration*scenario.tickSeconds);
  const left=Math.min(current,progress);
  const width=Math.abs(progress-current);
  timeline.style.setProperty("--preview-left",`${left*100}%`);
  timeline.style.setProperty("--preview-width",`${width*100}%`);
  timeline.style.setProperty("--preview-x",`${THREE.MathUtils.clamp(progress*100,2.5,97.5)}%`);
  timelinePreview.textContent=formatTime(progress*scenario.duration*scenario.tickSeconds);
  timeline.classList.add("previewing");
  timeline.classList.toggle("preview-before",progress<current);
}

function stretchTimeline(clientX:number){
  const rect=timeline.getBoundingClientRect();
  const overflowLeft=Math.max(0,rect.left-clientX);
  const overflowRight=Math.max(0,clientX-rect.right);
  const overflow=Math.max(overflowLeft,overflowRight);
  const direction=overflowLeft>overflowRight?-1:overflowRight>0?1:0;
  const strength=Math.sqrt(Math.min(1,overflow/2000));
  timeline.style.setProperty("--stretch-x",String(1+strength*.3));
  timeline.style.setProperty("--stretch-y",String(Math.max(.82,1-strength*.3)));
  timeline.style.setProperty("--stretch-shift",`${direction*strength*10}px`);
  timeline.style.setProperty("--stretch-origin",direction<0?"100%":direction>0?"0%":"50%");
}

function releaseTimeline(){
  timelineDragging=false;
  timelinePointerId=null;
  timeline.classList.remove("dragging");
  timeline.style.setProperty("--stretch-x","1");
  timeline.style.setProperty("--stretch-y","1");
  timeline.style.setProperty("--stretch-shift","0px");
  timeline.style.setProperty("--stretch-origin","50%");
}

function wireEvents(){
  playButton.addEventListener("click",togglePlay);

  timeline.addEventListener("pointerenter",event=>previewAt(progressAt(event.clientX)));
  timeline.addEventListener("pointerleave",()=>{if(!timelineDragging)timeline.classList.remove("previewing","preview-before")});
  timeline.addEventListener("pointerdown",event=>{
    if(event.pointerType==="mouse"&&event.button!==0)return;
    event.preventDefault();
    timelineDragging=true;timelinePointerId=event.pointerId;timeline.setPointerCapture(event.pointerId);timeline.classList.add("dragging");
    const progress=progressAt(event.clientX);previewAt(progress);seekToProgress(progress);
  });
  timeline.addEventListener("pointermove",event=>{
    const progress=progressAt(event.clientX);previewAt(progress);
    if(!timelineDragging||timelinePointerId!==event.pointerId)return;
    stretchTimeline(event.clientX);seekToProgress(progress);
  });
  const endDrag=(event:PointerEvent)=>{
    if(timelinePointerId!==null&&event.pointerId!==timelinePointerId)return;
    if(timeline.hasPointerCapture(event.pointerId))timeline.releasePointerCapture(event.pointerId);
    releaseTimeline();
  };
  timeline.addEventListener("pointerup",endDrag);timeline.addEventListener("pointercancel",endDrag);timeline.addEventListener("lostpointercapture",releaseTimeline);
  timeline.addEventListener("keydown",event=>{
    const total=scenario.duration*scenario.tickSeconds;
    if(event.code==="Space"){event.preventDefault();event.stopPropagation();togglePlay();return}
    if(event.key==="Home")elapsedSeconds=0;
    else if(event.key==="End")elapsedSeconds=total;
    else if(event.key==="ArrowLeft")elapsedSeconds=Math.max(0,elapsedSeconds-5);
    else if(event.key==="ArrowRight")elapsedSeconds=Math.min(total,elapsedSeconds+5);
    else return;
    event.preventDefault();updateWorld(elapsedSeconds/scenario.tickSeconds);
  });
  canvas.addEventListener("pointerdown",event=>{const rect=canvas.getBoundingClientRect();pointer.x=(event.clientX-rect.left)/rect.width*2-1;pointer.y=-(event.clientY-rect.top)/rect.height*2+1;raycaster.setFromCamera(pointer,activeCamera());const hit=raycaster.intersectObjects(Array.from(robotObjects.values()),true)[0];if(hit){let object:THREE.Object3D|null=hit.object;while(object&&!object.userData.robotId)object=object.parent;if(object?.userData.robotId)selectRobot(object.userData.robotId)}});
  q<HTMLSelectElement>("#scenario-select").addEventListener("change", event => loadScenario((event.currentTarget as HTMLSelectElement).value));
  document.querySelectorAll<HTMLButtonElement>("[data-camera]").forEach(button => button.addEventListener("click", () => setCameraMode(button.dataset.camera ?? "bird")));
  document.querySelectorAll<HTMLButtonElement>("[data-compare]").forEach(button => button.addEventListener("click", () => setCompareMode(button.dataset.compare as "without" | "with")));
  const replayIntro = () => {
    introStartedAt=performance.now();introActive=true;setCameraMode("cinematic");
  };
  q("#replay-intro").addEventListener("click",replayIntro);
  q("#restart").addEventListener("click",()=>{elapsedSeconds=0; comparisonSeconds=0; playing=true; syncPlayControl()});
  q("#camera-select").addEventListener("change",event=>setCameraMode((event.target as HTMLSelectElement).value));
  q("#speed").addEventListener("change",event=>{playbackSpeed=Number((event.target as HTMLSelectElement).value)});
  q<HTMLButtonElement>("#links-toggle").addEventListener("click", event => {
    linksEnabled = !linksEnabled;
    const button = event.currentTarget as HTMLButtonElement;
    button.textContent = `links / ${linksEnabled ? "on" : "off"}`;
    button.setAttribute("aria-pressed", String(linksEnabled));
    button.classList.toggle("active", linksEnabled);
    peerOverlay.visible = linksEnabled && scenario.id === "peer-network";
  });

  addEventListener("keydown",event=>{if(event.code==="Space"){event.preventDefault();togglePlay()}if(event.key.toLowerCase()==="r"){elapsedSeconds=0;playing=true;updateWorld(0);syncPlayControl()}const map:Record<string,string>={"1":"bird","2":"explore","3":"follow"};if(map[event.key])setCameraMode(map[event.key])});
  addEventListener("resize",()=>{
    camera.aspect=innerWidth/innerHeight;camera.updateProjectionMatrix();
    const aspect=innerWidth/innerHeight;const vertical=72;birdCamera.left=-vertical*aspect/2;birdCamera.right=vertical*aspect/2;birdCamera.top=vertical/2;birdCamera.bottom=-vertical/2;birdCamera.updateProjectionMatrix();
    renderer.setSize(innerWidth,innerHeight);activePixelRatio=presentationPixelRatio();renderer.setPixelRatio(activePixelRatio);frameSampleSeconds=0;frameSampleCount=0;
  });
}

async function start(){
  manifest=await fetch("/data/manifest.json").then(response=>response.json()) as Manifest;
  const scenarioSelect=q<HTMLSelectElement>("#scenario-select");
  scenarioSelect.innerHTML=manifest.scenarios.map((item,index)=>`<option value="${item.id}">${String(index+1).padStart(2,"0")} · ${item.title}</option>`).join("");
  scenarioSelect.value=manifest.default;
  await loadWarehouseModel();robotTemplate=await loadRobotModel();
  if ("compileAsync" in renderer) await renderer.compileAsync(scene, camera);
  q("#loading-status").textContent="Synchronising deterministic traces";await loadScenario(manifest.default);wireEvents();
  introStartedAt=performance.now();introActive=true;setCameraMode("cinematic");
  setTimeout(()=>q("#loading").classList.add("done"),350);
  renderer.setAnimationLoop(()=>{
    const delta=Math.min(clock.getDelta(),.15);adaptPixelRatio(delta);if(playing&&!introActive&&!timelineDragging&&!(scenario.id==="conflict-resolution"&&compareMode==="without")){elapsedSeconds+=delta*playbackSpeed;if(elapsedSeconds>=scenario.duration*scenario.tickSeconds){elapsedSeconds=scenario.duration*scenario.tickSeconds;playing=false;syncPlayControl()}}
    if(playing&&!timelineDragging&&!introActive&&compareMode==="without")comparisonSeconds+=delta*playbackSpeed;
    const tick=elapsedSeconds/scenario.tickSeconds;updateWorld(tick);updateCamera(delta);updatePeerOverlay(clock.elapsedTime);updateScenarioOverlays(tick,clock.elapsedTime);updateExplanation(tick,clock.elapsedTime);
    if(clock.elapsedTime-lastInterfaceUpdate>.16){updateInterface(tick);lastInterfaceUpdate=clock.elapsedTime}
    if(controls.enabled) controls.update();if(birdControls.enabled) birdControls.update();renderer.render(scene,activeCamera());
  });
}

start().catch(error=>{console.error(error);q("#loading-status").textContent="Could not load the digital twin — check the console"});
if (import.meta.hot) {
  import.meta.hot.dispose(() => {
    renderer.setAnimationLoop(null);
  });
}
