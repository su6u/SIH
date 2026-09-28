import * as THREE from "three";

export function woodFloor() {
  const material = new THREE.MeshStandardMaterial({ color: 0xffffff, roughness: .78, metalness: 0 });
  material.onBeforeCompile = shader => {
    shader.vertexShader = "varying vec3 woodPosition;\n" + shader.vertexShader;
    shader.vertexShader = shader.vertexShader.replace("#include <begin_vertex>", "#include <begin_vertex>\nwoodPosition = (modelMatrix * vec4(position, 1.0)).xyz;");
    shader.fragmentShader = "varying vec3 woodPosition;\n" + shader.fragmentShader;
    shader.fragmentShader = shader.fragmentShader.replace("#include <color_fragment>", `
      #include <color_fragment>
      vec2 p = woodPosition.xz;
      float boardWidth = .62;
      float boardLength = 5.6;
      float row = floor(p.y / boardWidth);
      float offset = mod(row, 2.0) * boardLength * .5;
      float board = floor((p.x + offset) / boardLength);
      float seed = fract(sin(row * 127.1 + board * 311.7) * 43758.5453);
      float across = fract(p.y / boardWidth);
      float along = fract((p.x + offset) / boardLength);
      float grain = sin(p.y * 84.0 + sin(p.x * 1.45 + seed * 1.7) * 1.5);
      float fine = sin(p.y * 310.0 + p.x * 1.15);
      float seam = smoothstep(0.0, .018, across) * smoothstep(0.0, .018, 1.0-across)
                 * smoothstep(0.0, .004, along) * smoothstep(0.0, .004, 1.0-along);
      float boardTone = .985 + seed * .03;
      vec3 oak = vec3(.285, .205, .135) * boardTone;
      diffuseColor.rgb *= oak * (1.0 + grain * .014 + fine * .004) * mix(.86, 1.0, seam);
    `);
  };
  return material;
}
