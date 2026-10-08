// The 3D preview of an avatar model in the Avatar tab.
//
// This is a module, loaded separately from app.js, so that if 3D is not
// available (no WebGL, or the libraries fail to load) the rest of the
// window is unaffected: app.js simply finds no viewer and says so.
//
// The model file is untrusted. It is only ever parsed as a 3D model by
// the loader; nothing in it is run or inserted into the page.

import * as THREE from "three";
import { GLTFLoader } from "three/addons/loaders/GLTFLoader.js";
import { OrbitControls } from "three/addons/controls/OrbitControls.js";
import { VRMLoaderPlugin, VRMUtils } from "@pixiv/three-vrm";

const canvas = document.getElementById("avatar-canvas");

let renderer = null;
let scene = null;
let camera = null;
let controls = null;
let last = null;
let current = null;
let frame = null;
let loads = 0;

function setUp() {
  if (renderer) return;

  renderer = new THREE.WebGLRenderer({ canvas, antialias: true, alpha: false });
  renderer.setPixelRatio(Math.min(window.devicePixelRatio || 1, 2));
  renderer.outputColorSpace = THREE.SRGBColorSpace;

  scene = new THREE.Scene();
  scene.background = new THREE.Color(0x0b0c10);
  scene.add(new THREE.AmbientLight(0xffffff, 1.2));
  const sun = new THREE.DirectionalLight(0xffffff, 1.8);
  sun.position.set(1, 2, 2);
  scene.add(sun);

  camera = new THREE.PerspectiveCamera(30, 3 / 4, 0.1, 50);
  controls = new OrbitControls(camera, canvas);
  controls.enableDamping = true;
  controls.enablePan = false;
}

// Seconds since the last frame.
function elapsed() {
  const now = performance.now();
  const seconds = last === null ? 0 : (now - last) / 1000;
  last = now;
  return seconds;
}

function fitCanvas() {
  const width = canvas.clientWidth;
  const height = canvas.clientHeight;
  if (!width || !height) return;

  const size = renderer.getSize(new THREE.Vector2());
  if (size.x !== width || size.y !== height) {
    renderer.setSize(width, height, false);
    camera.aspect = width / height;
    camera.updateProjectionMatrix();
  }
}

// Stand the camera back far enough to see the whole figure.
function frameModel(object) {
  const box = new THREE.Box3().setFromObject(object);
  const size = box.getSize(new THREE.Vector3());
  const center = box.getCenter(new THREE.Vector3());
  const height = Math.max(size.y, 0.5);
  const distance = (height / 2 / Math.tan((camera.fov * Math.PI) / 360)) * 1.25;

  camera.position.set(center.x, center.y, center.z + distance);
  controls.target.copy(center);
  controls.minDistance = distance * 0.2;
  controls.maxDistance = distance * 3;
  controls.update();
}

function draw() {
  frame = requestAnimationFrame(draw);

  // Nothing is drawn while the Avatar tab is not showing.
  if (canvas.offsetParent === null) {
    last = null;
    return;
  }

  const seconds = Math.min(elapsed(), 0.1);
  if (current) current.update(seconds);
  controls.update();
  fitCanvas();
  renderer.render(scene, camera);
}

function clear() {
  loads += 1;

  if (frame !== null) {
    cancelAnimationFrame(frame);
    frame = null;
  }

  if (current) {
    scene.remove(current.scene);
    VRMUtils.deepDispose(current.scene);
    current = null;
  }

  if (renderer) renderer.clear();
}

// Load a model and show it. Resolves with the names of the expressions
// the model has; rejects with an Error whose message can be shown.
async function show(url, onProgress) {
  try {
    setUp();
  } catch (error) {
    throw new Error("3D graphics are not available in this window.");
  }

  clear();
  const mine = loads;

  const loader = new GLTFLoader();
  loader.register((parser) => new VRMLoaderPlugin(parser));

  let gltf;
  try {
    gltf = await loader.loadAsync(url, (event) => {
      if (onProgress && event.total) onProgress(event.loaded / event.total);
    });
  } catch (error) {
    throw new Error("The model could not be loaded.");
  }

  // Another model was asked for while this one was loading.
  if (mine !== loads) return null;

  const vrm = gltf.userData.vrm;
  if (!vrm) throw new Error("The file loaded, but it is not a VRM avatar.");

  // Older VRM files face the other way.
  VRMUtils.rotateVRM0(vrm);
  scene.add(vrm.scene);
  current = vrm;
  fitCanvas();
  frameModel(vrm.scene);
  draw();

  const manager = vrm.expressionManager;
  return {
    expressions: manager ? manager.expressions.map((e) => e.expressionName) : [],
  };
}

function setExpression(name) {
  const manager = current && current.expressionManager;
  if (!manager) return;

  manager.expressions.forEach((expression) => {
    manager.setValue(expression.expressionName, 0);
  });
  if (name) manager.setValue(name, 1);
}

window.freyaAvatarView = { show, setExpression, clear };
window.dispatchEvent(new Event("freya-avatar-view-ready"));
