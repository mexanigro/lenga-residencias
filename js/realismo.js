// Capa de realismo del recorrido 3D. El modelo horneado es mate: le faltan los reflejos y brillos que dependen de dónde
// se pare uno, y eso lo hace ver "de videojuego". Dos agregados:
//  · Panoramas de Cycles proyectados: cerca del punto de vista de cada ambiente, cada superficie toma su color del
//    render 360° de Cycles (con reflejos, brillos y vidrios), proyectado desde donde se renderizó. Un cubo de
//    distancias de cada punto decide qué ve el panorama; lo que no ve (detrás de un mueble) sigue con el horneado.
//    Al alejarse, el panorama se funde con el horneado (como en Matterport).
//  · Reflejo del piso en tiempo real: la escena espejada bajo el piso, desenfocada y con Fresnel (el piso laqueado
//    refleja más cuanto más rasante se lo mira). Solo donde se ve el horneado; el panorama ya trae los suyos.
import * as THREE from 'three';

// m: a esta distancia del punto de vista el panorama se ve entero / desaparece. Corto a propósito: lejos del punto,
// lo que el panorama no ve (detrás de un mueble) crece y se nota el horneado; ahí manda el modelo con su reflejo.
const NEAR = 0.25, FAR = 1.2;
const PREFETCH = 3.0; // m: a esta distancia se empieza a bajar (y a subir a la placa: ~40 ms una vez)
const GLOSS = 0.9; // intensidad del reflejo del piso (sobre el Fresnel del barniz)

const GLSL = /* glsl */ `
uniform sampler2D uPanoA, uPanoB, uRefl;
uniform samplerCube uDepthA, uDepthB;
uniform vec3 uCA, uCB;
uniform vec2 uW;
uniform mat4 uReflM;
uniform float uReflOn, uReflLod, uSoft;
varying vec3 vLW;
vec3 lengaPano(sampler2D p, samplerCube dc, vec3 c, out float vis) {
  vec3 d = vLW - c;
  float dist = length(d);
  vec3 dir = d / dist;
  // cinco muestras alrededor: el borde de lo que no se ve se funde en vez de recortarse
  vec3 t1 = normalize(cross(dir, abs(dir.y) < 0.9 ? vec3(0.0, 1.0, 0.0) : vec3(1.0, 0.0, 0.0))), t2 = cross(dir, t1);
  float bias = 0.02 + 0.012 * dist;
  vis = 0.0;
  for (int i = 0; i < 5; i++) {
    vec2 o = i == 0 ? vec2(0.0) : vec2(i == 1 ? 1.0 : i == 2 ? -1.0 : 0.0, i == 3 ? 1.0 : i == 4 ? -1.0 : 0.0);
    vis += dist <= texture(dc, normalize(dir + (o.x * t1 + o.y * t2) * uSoft)).r + bias ? 0.2 : 0.0;
  }
  vec2 uv = vec2(atan(dir.x, -dir.z) * 0.1591549 + 0.5, asin(clamp(dir.y, -1.0, 1.0)) * 0.3183099 + 0.5);
  return texture(p, uv).rgb;
}
`;
const APPLY = /* glsl */ `
{
  vec3 n = normalize(cross(dFdx(vLW), dFdy(vLW)));
  float va = 0.0, vb = 0.0;
  vec3 pa = vec3(0.0), pb = vec3(0.0);
  if (uW.x > 0.001) pa = lengaPano(uPanoA, uDepthA, uCA, va);
  if (uW.y > 0.001) pb = lengaPano(uPanoB, uDepthB, uCB, vb);
  float wa = uW.x * va, wb = uW.y * vb, wp = min(1.0, wa + wb);
  vec3 col = diffuseColor.rgb * (1.0 - wp) + (wa * pa + wb * pb) / max(wa + wb, 1e-4) * wp;
  vec4 rc = uReflM * vec4(vLW, 1.0);
  vec3 refl = textureLod(uRefl, rc.xy / rc.w, uReflLod).rgb;
  float floorMask = uReflOn * step(0.97, abs(n.y)) * step(vLW.y, 0.006) * step(0.03, vLW.z); // piso interior, sin alfombras ni balcón
  float ct = clamp(normalize(cameraPosition - vLW).y, 0.0, 1.0);
  float F = (0.04 + 0.96 * pow(1.0 - ct, 5.0)) * ${GLOSS.toFixed(2)} * floorMask * (1.0 - wp);
  diffuseColor.rgb = mix(col, refl, F);
}
`;

export function createRealism(renderer, scene, camera, { lite, captures, hide }) {
  const dummy = new THREE.DataTexture(new Uint8Array([0, 0, 0, 255]), 1, 1);
  dummy.needsUpdate = true;
  const dummyCube = new THREE.WebGLCubeRenderTarget(1).texture;
  const U = {
    uPanoA: { value: dummy }, uPanoB: { value: dummy }, uDepthA: { value: dummyCube }, uDepthB: { value: dummyCube },
    uCA: { value: new THREE.Vector3() }, uCB: { value: new THREE.Vector3() }, uW: { value: new THREE.Vector2() },
    uRefl: { value: dummy }, uReflM: { value: new THREE.Matrix4() }, uReflOn: { value: 0 }, uReflLod: { value: 2.3 }, uSoft: { value: 0.006 },
  };

  // los materiales horneados reciben la capa (todos comparten el mismo programa)
  function patch(mat) {
    mat.onBeforeCompile = (sh) => {
      Object.assign(sh.uniforms, U);
      sh.vertexShader = 'varying vec3 vLW;\n' + sh.vertexShader.replace('#include <project_vertex>',
        '#include <project_vertex>\n  vLW = (modelMatrix * vec4(transformed, 1.0)).xyz;');
      sh.fragmentShader = GLSL + sh.fragmentShader.replace('#include <map_fragment>', '#include <map_fragment>\n' + APPLY);
    };
    mat.customProgramCacheKey = () => 'lenga-realismo';
  }

  /* ---------- panoramas: dónde se renderizó cada uno, qué ve y su textura ---------- */
  // Blender (x, y) a la altura de los ojos → Three.js (x, ojos, −y)
  const caps = captures.map(({ key, pos, eye, url }) => ({ key, url, c: new THREE.Vector3(pos[0], eye, -pos[1]), tex: null, depth: null, loading: null, w: 0, slot: -1 }));
  const depthMat = new THREE.ShaderMaterial({
    uniforms: { uC: { value: new THREE.Vector3() } },
    vertexShader: 'varying vec3 vW; void main() { vec4 w = modelMatrix * vec4(position, 1.0); vW = w.xyz; gl_Position = projectionMatrix * viewMatrix * w; }',
    fragmentShader: 'uniform vec3 uC; varying vec3 vW; void main() { gl_FragColor = vec4(length(vW - uC)); }',
    side: THREE.DoubleSide,
  });
  const DS = lite ? 256 : 512; // cubo de distancias (RGBA de 16 bits: ~12 MB cada uno en escritorio)
  function hideAll(on) { for (const o of hide()) o.visible = on; }
  // distancia a la primera superficie en cada dirección, vista desde donde se renderizó el panorama
  function depthOf(cap) {
    const rt = new THREE.WebGLCubeRenderTarget(DS, { type: THREE.HalfFloatType, minFilter: THREE.NearestFilter, magFilter: THREE.NearestFilter, generateMipmaps: false });
    const cc = new THREE.CubeCamera(0.03, 60, rt);
    cc.position.copy(cap.c);
    depthMat.uniforms.uC.value.copy(cap.c);
    const bg = scene.background;
    scene.background = null;
    scene.overrideMaterial = depthMat;
    hideAll(false);
    cc.update(renderer, scene);
    hideAll(true);
    scene.overrideMaterial = null;
    scene.background = bg;
    return rt;
  }
  const bitmaps = new THREE.ImageBitmapLoader().setOptions({ imageOrientation: 'flipY' }); // se decodifica fuera del hilo principal
  function fetchPano(cap) {
    if (cap.loading) return cap.loading;
    cap.loading = bitmaps.loadAsync(cap.url).then((bmp) => {
      const t = new THREE.Texture(bmp);
      t.colorSpace = THREE.SRGBColorSpace;
      t.flipY = false;
      t.generateMipmaps = false; // sin mipmaps: no aparece la costura del panorama
      t.minFilter = t.magFilter = THREE.LinearFilter;
      t.needsUpdate = true;
      renderer.initTexture(t);
      cap.depth ??= depthOf(cap);
      cap.tex = t;
    }).catch((e) => { console.warn('panorama', cap.key, e); cap.loading = null; });
    return cap.loading;
  }
  // como mucho cuatro panoramas en la placa de video (~75 MB cada uno; dos de ~32 MB en celulares): se suelta el más lejano
  const KEEP = lite ? 2 : 4;
  function trim(p) {
    const held = caps.filter((c) => c.tex).sort((a, b) => a.c.distanceToSquared(p) - b.c.distanceToSquared(p));
    for (const c of held.slice(KEEP)) if (c.w < 0.001 && c.slot < 0) {
      c.tex.image.close?.();
      c.tex.dispose();
      c.tex = null;
      c.loading = null;
    }
  }

  /* ---------- reflejo del piso ---------- */
  const reflRT = new THREE.WebGLRenderTarget(1, 1, {
    type: THREE.HalfFloatType, generateMipmaps: true, minFilter: THREE.LinearMipmapLinearFilter, depthBuffer: true,
  });
  const vcam = new THREE.PerspectiveCamera();
  const N = new THREE.Vector3(0, 1, 0), O = new THREE.Vector3(), plane = new THREE.Plane(), clip = new THREE.Vector4(), q = new THREE.Vector4();
  const view = new THREE.Vector3(), look = new THREE.Vector3(), target = new THREE.Vector3(), rot = new THREE.Matrix4();
  const camPos = new THREE.Vector3();
  const scale = lite ? 0.35 : 0.5;
  function renderReflection() {
    camPos.setFromMatrixPosition(camera.matrixWorld);
    if (camPos.y <= 0) return false;
    const db = renderer.getDrawingBufferSize(new THREE.Vector2());
    const w = Math.max(1, Math.round(db.x * scale)), h = Math.max(1, Math.round(db.y * scale));
    if (reflRT.width !== w || reflRT.height !== h) reflRT.setSize(w, h);
    // cámara espejada respecto del piso (y = 0), como el Reflector de Three.js
    view.copy(O).sub(camPos).reflect(N).negate().add(O);
    rot.extractRotation(camera.matrixWorld);
    look.set(0, 0, -1).applyMatrix4(rot).add(camPos);
    target.copy(O).sub(look).reflect(N).negate().add(O);
    vcam.position.copy(view);
    vcam.up.set(0, 1, 0).applyMatrix4(rot).reflect(N);
    vcam.lookAt(target);
    vcam.far = camera.far;
    vcam.updateMatrixWorld();
    vcam.projectionMatrix.copy(camera.projectionMatrix);
    U.uReflM.value.set(0.5, 0, 0, 0.5, 0, 0.5, 0, 0.5, 0, 0, 0.5, 0.5, 0, 0, 0, 1)
      .multiply(vcam.projectionMatrix).multiply(vcam.matrixWorldInverse);
    // plano de recorte oblicuo: no se dibuja nada debajo del piso
    plane.setFromNormalAndCoplanarPoint(N, O).applyMatrix4(vcam.matrixWorldInverse);
    clip.set(plane.normal.x, plane.normal.y, plane.normal.z, plane.constant);
    const P = vcam.projectionMatrix.elements;
    q.set((Math.sign(clip.x) + P[8]) / P[0], (Math.sign(clip.y) + P[9]) / P[5], -1, (1 + P[10]) / P[14]);
    clip.multiplyScalar(2 / clip.dot(q));
    P[2] = clip.x; P[6] = clip.y; P[10] = clip.z + 1; P[14] = clip.w;
    // sin leer su propia textura mientras se dibuja
    U.uRefl.value = dummy;
    U.uReflOn.value = 0;
    hideAll(false);
    const prev = renderer.getRenderTarget();
    renderer.setRenderTarget(reflRT);
    renderer.clear();
    renderer.render(scene, vcam);
    renderer.setRenderTarget(prev);
    hideAll(true);
    U.uRefl.value = reflRT.texture;
    return true;
  }

  /* ---------- cuadro a cuadro ---------- */
  let panoWeight = 0, held = null;
  function update(dt) {
    camPos.setFromMatrixPosition(camera.matrixWorld);
    // peso de cada panorama según la distancia (en planta) al punto donde se renderizó
    for (const c of caps) {
      const d = Math.hypot(c.c.x - camPos.x, c.c.z - camPos.z);
      if (d < PREFETCH) fetchPano(c);
      const want = c.tex ? 1 - THREE.MathUtils.smoothstep(d, NEAR, FAR) : 0;
      c.w += (want - c.w) * Math.min(1, dt * 5); // se funde, no aparece de golpe
      if (c.w < 0.002 && want === 0) c.w = 0;
    }
    // dos lugares en el shader: los conserva quien los tiene mientras tenga peso
    const best = caps.filter((c) => c.w > 0).sort((a, b) => b.w - a.w).slice(0, 2);
    for (const c of caps) if (c.slot >= 0 && !best.includes(c)) c.slot = -1;
    for (const c of best) if (c.slot < 0) c.slot = [0, 1].find((s) => !best.some((o) => o !== c && o.slot === s));
    let wA = 0, wB = 0;
    for (const c of best) {
      if (c.slot === 0) { U.uPanoA.value = c.tex; U.uDepthA.value = c.depth.texture; U.uCA.value.copy(c.c); wA = c.w; }
      else { U.uPanoB.value = c.tex; U.uDepthB.value = c.depth.texture; U.uCB.value.copy(c.c); wB = c.w; }
    }
    const sum = wA + wB;
    if (sum > 1) { wA /= sum; wB /= sum; }
    U.uW.value.set(wA, wB);
    if (!wA) { U.uPanoA.value = dummy; U.uDepthA.value = dummyCube; }
    if (!wB) { U.uPanoB.value = dummy; U.uDepthB.value = dummyCube; }
    panoWeight = Math.min(1, wA + wB);
    // con el panorama entero a la vista el reflejo no se ve: no se dibuja
    U.uReflOn.value = panoWeight < 0.97 && renderReflection() ? 1 : 0;
    if (!U.uReflOn.value) U.uRefl.value = dummy;
    trim(camPos);
  }

  return {
    patch,
    update,
    // el panorama del ambiente adonde se va, antes de llegar
    prefetch(key) { const c = caps.find((x) => x.key === key); if (c) fetchPano(c); },
    get panoWeight() { return panoWeight; },
    // para otra pasada (el espejo del baño): solo el horneado, sin panoramas ni reflejo del piso
    suspend() { held = [U.uW.value.clone(), U.uReflOn.value, U.uRefl.value]; U.uW.value.set(0, 0); U.uReflOn.value = 0; U.uRefl.value = dummy; },
    resume() { if (held) { U.uW.value.copy(held[0]); U.uReflOn.value = held[1]; U.uRefl.value = held[2]; held = null; } },
  };
}
