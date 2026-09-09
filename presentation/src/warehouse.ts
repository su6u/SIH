import * as THREE from "three";

const material = (color: number, roughness = .55, metalness = .05) => new THREE.MeshStandardMaterial({ color, roughness, metalness });

function box(name: string, size: [number, number, number], position: [number, number, number], mat: THREE.Material, shadows = true) {
  const mesh = new THREE.Mesh(new THREE.BoxGeometry(...size), mat);
  mesh.name = name;
  mesh.position.set(...position);
  mesh.castShadow = shadows;
  mesh.receiveShadow = shadows;
  return mesh;
}

function label(text: string, width = 512, color = "#dffcf6") {
  const canvas = document.createElement("canvas");
  canvas.width = width; canvas.height = 128;
  const context = canvas.getContext("2d")!;
  context.clearRect(0, 0, width, 128);
  context.fillStyle = color;
  context.font = "700 48px Arial";
  context.textAlign = "center";
  context.fillText(text, width / 2, 78);
  const texture = new THREE.CanvasTexture(canvas);
  texture.colorSpace = THREE.SRGBColorSpace;
  const sprite = new THREE.Sprite(new THREE.SpriteMaterial({ map: texture, transparent: true, depthWrite: false }));
  sprite.scale.set(6, 1.5, 1);
  return sprite;
}

function makeRack(x: number, z: number, index: number) {
  const group = new THREE.Group();
  group.name = `Rack ${String(index + 1).padStart(2, "0")}`;
  const steel = material(0x355465, .34, .68);
  const beam = material(0xd67e31, .42, .45);
  const shelf = material(0x65737a, .55, .5);
  const timber = material(0x9b7049, .82, .02);
  const cartonMats = [material(0xb78a5f, .9), material(0x9f7653, .92), material(0xc4996b, .9)];
  const width = 5.8, depth = 7.2, height = 6.8;
  for (const px of [-width / 2, width / 2]) for (const pz of [-depth / 2, 0, depth / 2]) {
    group.add(box("upright", [.16, height, .16], [px, height / 2, pz], steel));
    group.add(box("foot", [.46, .12, .5], [px, .06, pz], beam));
  }
  for (const level of [1.25, 2.95, 4.65, 6.35]) {
    for (const pz of [-depth / 2, depth / 2]) group.add(box("orange beam", [width + .18, .18, .18], [0, level, pz], beam));
    group.add(box("shelf deck", [width, .07, depth], [0, level + .07, 0], shelf, false));
  }
  // Cross braces keep the silhouettes recognisably industrial.
  for (const side of [-1, 1]) for (let section = 0; section < 2; section++) {
    const brace = box("diagonal brace", [.08, 3.55, .08], [side * width / 2, 1.8 + section * 3.3, 0], steel, false);
    brace.rotation.x = Math.PI / 3.1 * (section ? -1 : 1);
    group.add(brace);
  }
  for (let level = 0; level < 3; level++) for (let bay = 0; bay < 3; bay++) {
    if ((index + level + bay) % 5 === 0) continue;
    const cy = 1.72 + level * 1.7;
    const cz = -2.35 + bay * 2.35;
    group.add(box("pallet", [4.95, .12, 1.8], [0, cy - .35, cz], timber, false));
    for (const side of [-1, 1]) {
      const carton = box("carton", [2.05, .68 + ((index + bay) % 2) * .18, 1.55], [side * 1.15, cy, cz], cartonMats[(index + level + bay + (side > 0 ? 1 : 0)) % cartonMats.length], false);
      group.add(carton);
      group.add(box("parcel tape", [.09, .71, 1.57], [side * 1.15, cy, cz], material(0xd8b88b, .8), false));
    }
  }
  const sign = label(`R-${String(index + 1).padStart(2, "0")}`, 256, "#eafbf7");
  sign.position.set(0, 7.35, -depth / 2);
  sign.scale.set(2.4, .6, 1);
  group.add(sign);
  group.position.set(x, 0, z);
  return group;
}

function conveyor(x: number, z: number, length: number, rotate = false) {
  const group = new THREE.Group();
  const dark = material(0x25343b, .42, .62);
  const rail = material(0x65747b, .32, .76);
  const belt = box("conveyor belt", [length, .24, 1.6], [0, 1.05, 0], dark);
  group.add(belt);
  for (let p = -length / 2 + .4; p < length / 2; p += .65) {
    const roller = new THREE.Mesh(new THREE.CylinderGeometry(.11, .11, 1.48, 10), rail);
    roller.rotation.x = Math.PI / 2; roller.position.set(p, 1.2, 0); group.add(roller);
  }
  for (const px of [-length / 2 + .3, 0, length / 2 - .3]) for (const pz of [-.65, .65]) group.add(box("conveyor leg", [.11, 1, .11], [px, .5, pz], rail));
  group.position.set(x, 0, z);
  if (rotate) group.rotation.y = Math.PI / 2;
  return group;
}

export function createWarehouse(scene: THREE.Scene) {
  const world = new THREE.Group();
  world.name = "FC-01 warehouse";
  scene.add(world);
  const concrete = material(0x5a5c59, .74, .08);
  const outside = material(0x171d20, .9, 0);
  world.add(box("apron", [112, .35, 90], [25, -.28, 19], outside));
  const sections: [number, number, number, number][] = [[-18,-12,72,30],[-18,30,60,42],[-18,42,12,54]];
  sections.forEach(([x1,z1,x2,z2]) => world.add(box("polished concrete", [x2-x1,.28,z2-z1], [(x1+x2)/2,-.02,(z1+z2)/2], concrete)));

  const grid = new THREE.GridHelper(92, 92, 0x75817d, 0x4a5351);
  grid.position.set(27, .135, 9); (grid.material as THREE.Material).opacity = .14; (grid.material as THREE.Material).transparent = true; world.add(grid);
  const routeMat = new THREE.MeshStandardMaterial({color:0x3bb9a7,roughness:.48,emissive:0x163d38,emissiveIntensity:.35});
  world.add(box("autonomous arterial", [84,.018,1.15], [26,.145,-5.2], routeMat, false));
  world.add(box("pedestrian lane", [1.1,.02,57], [-14.5,.15,18], material(0xcba43f,.55), false));
  for (let x=-10;x<68;x+=4) world.add(box("lane dash", [2,.025,.1], [x,.16,-2.2], material(0xe9d26b,.6), false));

  const glass = new THREE.MeshPhysicalMaterial({color:0xabcfd2,roughness:.08,metalness:0,transmission:.78,transparent:true,opacity:.23,thickness:.18,ior:1.45,side:THREE.DoubleSide,depthWrite:false});
  const frame = material(0x273b47, .27, .76);
  const perimeter: [number,number][] = [[-18,-12],[72,-12],[72,30],[60,30],[60,42],[12,42],[12,54],[-18,54],[-18,-12]];
  perimeter.slice(0,-1).forEach((point,index) => {
    const next=perimeter[index+1], dx=next[0]-point[0], dz=next[1]-point[1], length=Math.hypot(dx,dz), angle=Math.atan2(dz,dx), cx=(point[0]+next[0])/2, cz=(point[1]+next[1])/2;
    const wall=box("transparent glass wall",[length,9,.09],[cx,4.5,cz],glass,false); wall.rotation.y=-angle; world.add(wall);
    const base=box("wall sill",[length,.22,.22],[cx,.12,cz],frame);base.rotation.y=-angle;world.add(base);
    const cap=box("wall cap",[length,.18,.2],[cx,9,cz],frame);cap.rotation.y=-angle;world.add(cap);
    for(let d=-length/2;d<=length/2;d+=6){const mullion=box("glass mullion",[.12,9,.16],[cx+Math.cos(angle)*d,4.5,cz+Math.sin(angle)*d],frame);mullion.rotation.y=-angle;world.add(mullion)}
  });
  for(const x of [-18,0,18,36,54,72]) world.add(box("roof beam",[.18,.22,42],[x,9,9],frame));
  for(const z of [-12,0,12,24,30]) world.add(box("roof beam",[90,.22,.18],[27,9,z],frame));
  const roof = new THREE.Group(); roof.name="glass roof";
  sections.forEach(([x1,z1,x2,z2]) => roof.add(box("transparent roof panel",[x2-x1,.08,z2-z1],[(x1+x2)/2,9.05,(z1+z2)/2],glass,false)));
  roof.visible=true; world.add(roof);

  const rackXs=[-9,3,15,27,39,51], rackZs=[0,12,24,36];
  rackZs.forEach((z,row)=>rackXs.forEach((x,col)=>world.add(makeRack(x,z,row*rackXs.length+col))));
  world.add(conveyor(26,-8.2,55)); world.add(conveyor(65,10,32,true));

  // Loading docks, charge points, work cells and safety details.
  for(let i=0;i<6;i++){
    const x=-8+i*13;
    world.add(box("dock door",[8,5,.32],[x,2.65,-11.8],material(0x55636a,.38,.55)));
    for(let y=.65;y<5;y+=.55) world.add(box("door slat",[7.7,.04,.34],[x,y,-12],material(0x829097,.35,.6),false));
    const dockLabel=label(`DOCK ${i+1}`,256,"#ffda78");dockLabel.position.set(x,6.3,-11.6);dockLabel.scale.set(3,.75,1);world.add(dockLabel);
  }
  for(let i=0;i<6;i++){
    const x=48+i*3.2;
    world.add(box("charger",[2.25,.08,2.25],[x,.18,27.5],material(0x243b40,.45,.45),false));
    world.add(box("charge glow",[1.5,.025,1.5],[x,.24,27.5],new THREE.MeshStandardMaterial({color:0x73ead4,emissive:0x2d9988,emissiveIntensity:1.2}),false));
  }
  for(let i=0;i<8;i++){
    const x=-10+i*8.3;
    world.add(box("packing bench",[5.4,1.05,2.2],[x,.55,49],material(0xc9c5b8,.7,.1)));
    world.add(box("bench carton",[1.2,.9,1.05],[x-.9,1.5,49],material(0xc39466,.88),false));
    world.add(box("monitor",[.7,.75,.08],[x+1.1,1.65,48.7],material(0x172127,.26,.25),false));
  }
  const entry=label("SWARMROUTE · FC—01",1024);entry.position.set(27,8,-11.65);entry.scale.set(18,2.25,1);world.add(entry);

  // Balanced practicals match the warm/neutral Blender grade. The previous
  // browser-only intensities clipped the mint enamel and made follow shots
  // read as white while still spending the same fill-light cost.
  const hemi=new THREE.HemisphereLight(0xb9d9dd,0x233036,.86);scene.add(hemi);
  const sun=new THREE.DirectionalLight(0xffe0bd,2.05);sun.position.set(-24,42,-30);sun.castShadow=true;sun.shadow.mapSize.set(2048,2048);sun.shadow.camera.left=-65;sun.shadow.camera.right=65;sun.shadow.camera.top=65;sun.shadow.camera.bottom=-65;sun.shadow.bias=-.0004;scene.add(sun);
  for(const [x,z] of [[-4,5],[22,5],[48,5],[-4,29],[22,29],[48,29]] as [number,number][]){const light=new THREE.PointLight(0xcdf6ef,7.5,25,2);light.position.set(x,8,z);scene.add(light);world.add(box("ceiling light",[5,.06,.35],[x,8.75,z],new THREE.MeshBasicMaterial({color:0xffe3bf}),false))}
  return { world, roof };
}

export function createHazardMarker() {
  const group = new THREE.Group(); group.name="active incident"; group.visible=false;
  const mat=new THREE.MeshBasicMaterial({color:0xff754f,transparent:true,opacity:.28,depthWrite:false,side:THREE.DoubleSide});
  const disc=new THREE.Mesh(new THREE.CircleGeometry(2.8,40),mat);disc.rotation.x=-Math.PI/2;disc.position.y=.18;group.add(disc);
  const ring=new THREE.Mesh(new THREE.RingGeometry(3,3.25,48),new THREE.MeshBasicMaterial({color:0xff9b6f,transparent:true,opacity:.9,side:THREE.DoubleSide}));ring.rotation.x=-Math.PI/2;ring.position.y=.2;ring.name="pulse";group.add(ring);
  return group;
}
