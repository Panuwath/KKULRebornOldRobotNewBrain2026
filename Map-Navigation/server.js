const express = require('express');
const path = require('path');
const cors = require('cors');
const fs = require('fs');

const app = express();
const PORT = process.env.PORT || 3000;

app.use(cors());
app.use(express.json());

// Serve static files
app.use(express.static(path.join(__dirname, 'public')));
app.use('/data', express.static(path.join(__dirname, 'data')));

// Load Graph Data
let graphData = null;
let roomsList = [];
let nodesMap = new Map();
let adjList = new Map();

function loadData() {
  try {
    const rawGraph = fs.readFileSync(path.join(__dirname, 'data', 'graph_data.json'), 'utf-8');
    graphData = JSON.parse(rawGraph);
    
    const rawRooms = fs.readFileSync(path.join(__dirname, 'data', 'rooms.json'), 'utf-8');
    roomsList = JSON.parse(rawRooms);

    // Build Maps for fast routing
    nodesMap.clear();
    adjList.clear();

    graphData.nodes.forEach(node => {
      nodesMap.set(node.id, node);
      adjList.set(node.id, []);
    });

    graphData.edges.forEach(edge => {
      if (adjList.has(edge.from) && adjList.has(edge.to)) {
        adjList.get(edge.from).push({
          to: edge.to,
          weight: edge.weight,
          type: edge.type,
          description: edge.description || ''
        });
      }
    });

    console.log(`Loaded ${nodesMap.size} nodes, ${graphData.edges.length} edges, ${roomsList.length} rooms.`);
  } catch (err) {
    console.error('Error loading graph data:', err);
  }
}

loadData();

// API: Reload graph data
app.get('/api/reload', (req, res) => {
  loadData();
  res.json({ success: true, nodes: nodesMap.size, edges: graphData.edges.length, rooms: roomsList.length });
});

// Smart Node Identifier Resolver
function resolveNode(query, defaultFallback = null) {
  if (!query) return defaultFallback;
  const q = String(query).trim().toLowerCase();

  // 1. Exact match ID
  if (nodesMap.has(q)) return nodesMap.get(q);

  // 2. Exact match code (e.g. "1102", "2201", "1401", "3206")
  for (const node of nodesMap.values()) {
    if (node.code && String(node.code).toLowerCase() === q) {
      return node;
    }
  }

  // 3. Special keywords
  if (q === 'toilet' || q === 'restroom' || q === 'wc' || q === 'ห้องน้ำ' || q === 'สุขา') {
    return { isSpecialType: 'restroom' };
  }
  if (q === 'cafe' || q === 'coffee' || q === 'amazon' || q === 'อเมซอน') {
    return nodesMap.get('r3200') || null;
  }
  if (q === 'circ' || q === 'ยืมคืน' || q === 'ยืม-คืน' || q === 'ยืมหนังสือ') {
    return nodesMap.get('r3206') || null;
  }
  if (q === 'ai' || q === 'ai clinic' || q === 'คลินิก ai') {
    return nodesMap.get('r3202') || null;
  }
  if (q === 'entrance' || q === 'ทางเข้า' || q === 'ประตูทางเข้า' || q === 'main') {
    return nodesMap.get('poi_f2_main_entrance') || null;
  }

  // 4. Fuzzy search in Thai name / English name / keywords
  for (const node of nodesMap.values()) {
    if (node.name_th && node.name_th.toLowerCase().includes(q)) return node;
    if (node.name_en && node.name_en.toLowerCase().includes(q)) return node;
    if (node.keywords && node.keywords.some(k => k.toLowerCase().includes(q))) return node;
  }

  return defaultFallback;
}

// Dijkstra Shortest Path Finder
function findPath(startId, goalId = null, targetType = null) {
  if (!nodesMap.has(startId)) return null;

  const distances = new Map();
  const previous = new Map();
  const visited = new Set();
  
  const queue = [{ id: startId, dist: 0 }];
  distances.set(startId, 0);

  let targetFound = null;

  while (queue.length > 0) {
    queue.sort((a, b) => a.dist - b.dist);
    const { id: u, dist: d } = queue.shift();

    if (visited.has(u)) continue;
    visited.add(u);

    if (goalId && u === goalId) {
      targetFound = u;
      break;
    }
    if (targetType && u !== startId) {
      const uNode = nodesMap.get(u);
      if (uNode && (uNode.type === targetType || (targetType === 'restroom' && uNode.category === 'restroom'))) {
        targetFound = u;
        break;
      }
    }

    const neighbors = adjList.get(u) || [];
    for (const edge of neighbors) {
      const v = edge.to;
      const weight = edge.weight;
      const newDist = d + weight;

      if (!distances.has(v) || newDist < distances.get(v)) {
        distances.set(v, newDist);
        previous.set(v, {
          from: u,
          type: edge.type,
          description: edge.description,
          weight: edge.weight
        });
        queue.push({ id: v, dist: newDist });
      }
    }
  }

  const finalGoal = goalId || targetFound;
  if (!finalGoal || !distances.has(finalGoal)) {
    return null;
  }

  // Reconstruct path
  const pathSteps = [];
  let curr = finalGoal;
  while (previous.has(curr)) {
    const prevInfo = previous.get(curr);
    pathSteps.push({
      from: nodesMap.get(prevInfo.from),
      to: nodesMap.get(curr),
      type: prevInfo.type,
      description: prevInfo.description,
      weight: prevInfo.weight
    });
    curr = prevInfo.from;
  }
  pathSteps.reverse();

  const allNodes = [nodesMap.get(startId), ...pathSteps.map(s => s.to)];
  const passedFloors = [...new Set(allNodes.map(n => n.floor))].sort((a, b) => a - b);

  // Generate Turn-by-turn Navigation Instructions
  const instructions = generateInstructions(pathSteps, nodesMap.get(startId), nodesMap.get(finalGoal));

  // Generate Speech Scripts for Zenbo Robot TTS
  const { speechText, stepSpeeches } = generateZenboSpeech(
    nodesMap.get(startId),
    nodesMap.get(finalGoal),
    Math.round(distances.get(finalGoal) * 10) / 10,
    Math.max(1, Math.ceil(distances.get(finalGoal) / 50)),
    instructions,
    passedFloors
  );

  return {
    start: nodesMap.get(startId),
    destination: nodesMap.get(finalGoal),
    totalDistanceMeters: Math.round(distances.get(finalGoal) * 10) / 10,
    estimatedMinutes: Math.max(1, Math.ceil(distances.get(finalGoal) / 50)),
    passedFloors,
    stepCount: instructions.length,
    speech_text: speechText,
    step_speeches: stepSpeeches,
    instructions,
    pathSteps,
    nodes: allNodes
  };
}

function generateInstructions(steps, startNode, endNode) {
  const instructions = [];
  if (steps.length === 0) {
    return [{
      stepNumber: 1,
      floor: startNode.floor,
      title: "คุณอยู่ที่จุดหมายแล้ว",
      detail: `ตำแหน่งปัจจุบันของคุณคือ ${startNode.name_th}`,
      icon: "check-circle",
      type: "arrival",
      nodeId: startNode.id
    }];
  }

  let stepNo = 1;
  instructions.push({
    stepNumber: stepNo++,
    floor: startNode.floor,
    title: `เริ่มต้นที่ ${startNode.name_th}`,
    detail: `ชั้น ${startNode.floor} - เตรียมตัวออกเดินทาง`,
    icon: "play",
    type: "start",
    nodeId: startNode.id
  });

  for (let i = 0; i < steps.length; i++) {
    const s = steps[i];
    const fromNode = s.from;
    const toNode = s.to;

    if (s.type === 'stairs' || s.type === 'elevator') {
      const isUp = toNode.floor > fromNode.floor;
      const verb = isUp ? 'ขึ้น' : 'ลง';
      const transportName = s.type === 'elevator' ? 'ลิฟต์' : 'บันได';
      
      instructions.push({
        stepNumber: stepNo++,
        floor: fromNode.floor,
        targetFloor: toNode.floor,
        title: `${verb}${transportName} ไปยังชั้น ${toNode.floor}`,
        detail: `ใช้ ${transportName} จากชั้น ${fromNode.floor} เพื่อเปลี่ยนไปยังชั้น ${toNode.floor} (${toNode.name_th})`,
        icon: s.type === 'elevator' ? 'elevator' : 'stairs',
        type: 'vertical',
        isUp,
        transport: s.type,
        nodeId: toNode.id
      });
    } else {
      if (toNode.id === endNode.id) {
        instructions.push({
          stepNumber: stepNo++,
          floor: toNode.floor,
          title: `ถึงจุดหมาย: ${toNode.name_th}`,
          detail: `ชั้น ${toNode.floor} - ${toNode.description || toNode.name_en}`,
          icon: "map-pin",
          type: "destination",
          nodeId: toNode.id
        });
      } else if (toNode.type === 'room' || toNode.type === 'landmark' || toNode.type === 'restroom') {
        instructions.push({
          stepNumber: stepNo++,
          floor: toNode.floor,
          title: `เดินผ่าน ${toNode.name_th}`,
          detail: `ชั้น ${toNode.floor} - จุดสังเกตระหว่างทาง`,
          icon: toNode.type === 'restroom' ? 'toilet' : 'navigation',
          type: "checkpoint",
          nodeId: toNode.id
        });
      }
    }
  }

  return instructions;
}

function generateZenboSpeech(startNode, endNode, distanceMeters, estimatedMinutes, instructions, passedFloors) {
  let speechText = "";
  
  if (startNode.floor === endNode.floor) {
    speechText = `กำลังนำทางจาก ${startNode.name_th} ไปยัง ${endNode.name_th} ชั้น ${endNode.floor} ครับ ระยะทางประมาณ ${distanceMeters} เมตร ใช้เวลาเดินประมาณ ${estimatedMinutes} นาที กรุณาเดินตามเส้นทางบนหน้าจอหรือเดินตาม Zenbo มาได้เลยครับ`;
  } else {
    const isUp = endNode.floor > startNode.floor;
    const direction = isUp ? "ขึ้น" : "ลง";
    speechText = `กำลังนำทางจาก ${startNode.name_th} ชั้น ${startNode.floor} ไปยัง ${endNode.name_th} ชั้น ${endNode.floor} ครับ โดยจะต้อง${direction}บันไดหรือลิฟต์ไปยังชั้น ${endNode.floor} ระยะทางรวมประมาณ ${distanceMeters} เมตร ใช้เวลาเดินประมาณ ${estimatedMinutes} นาที กรุณาเดินตามเส้นทางบนหน้าจอครับ`;
  }

  const stepSpeeches = instructions.map(inst => {
    if (inst.type === 'start') {
      return `เริ่มต้นการเดินทางที่ ${inst.title}`;
    } else if (inst.type === 'vertical') {
      return `${inst.title} ${inst.detail}`;
    } else if (inst.type === 'checkpoint') {
      return `${inst.title}`;
    } else if (inst.type === 'destination') {
      return `ถึงจุดหมาย ${endNode.name_th} ชั้น ${endNode.floor} เรียบร้อยแล้วครับ ขอบคุณครับ`;
    }
    return inst.title;
  });

  return { speechText, stepSpeeches };
}

// Helper to construct full Navigation Response supporting both top-level and data envelope
function buildNavigationResponse(req, route) {
  const host = req.headers.host || `localhost:${PORT}`;
  const protocol = req.protocol || 'http';
  const baseUrl = `${protocol}://${host}`;

  const startId = route.start.id;
  const destId = route.destination.id;

  const zenbo_display_url = `${baseUrl}/zenbo.html?from=${encodeURIComponent(startId)}&to=${encodeURIComponent(destId)}&autostart=true`;
  const map_display_url = `${baseUrl}/?from=${encodeURIComponent(startId)}&to=${encodeURIComponent(destId)}`;

  const payload = {
    start: route.start,
    destination: route.destination,
    totalDistanceMeters: route.totalDistanceMeters,
    total_distance_meters: route.totalDistanceMeters,
    estimatedMinutes: route.estimatedMinutes,
    estimated_minutes: route.estimatedMinutes,
    passedFloors: route.passedFloors,
    passed_floors: route.passedFloors,
    stepCount: route.stepCount,
    step_count: route.stepCount,
    speech_text: route.speech_text,
    step_speeches: route.step_speeches,
    instructions: route.instructions,
    pathSteps: route.pathSteps,
    path_steps: route.pathSteps,
    nodes: route.nodes,
    zenbo_display_url,
    map_display_url
  };

  return {
    success: true,
    data: payload,
    ...payload
  };
}

// API: Get all Floors metadata
app.get('/api/floors', (req, res) => {
  res.json({
    success: true,
    data: graphData.floors
  });
});

// API: Get all Rooms & POIs
app.get('/api/rooms', (req, res) => {
  const query = (req.query.q || '').trim().toLowerCase();
  const floor = req.query.floor ? parseInt(req.query.floor) : null;
  const category = req.query.category;

  let results = roomsList;

  if (floor) {
    results = results.filter(r => r.floor === floor);
  }

  if (category) {
    results = results.filter(r => r.category === category || r.type === category);
  }

  if (query) {
    results = results.filter(r => {
      const thMatch = (r.name_th || '').toLowerCase().includes(query);
      const enMatch = (r.name_en || '').toLowerCase().includes(query);
      const codeMatch = (r.code || '').toLowerCase().includes(query);
      const kwMatch = r.keywords && r.keywords.some(k => k.toLowerCase().includes(query));
      return thMatch || enMatch || codeMatch || kwMatch;
    });
  }

  res.json({
    success: true,
    count: results.length,
    data: results
  });
});

// Primary Navigation Route Handler
function handleNavigationRequest(req, res) {
  const fromParam = req.query.from || (req.body && req.body.from) || 'poi_f2_main_entrance';
  const toParam = req.query.to || (req.body && req.body.to);

  if (!toParam) {
    return res.status(400).json({
      success: false,
      error: 'Parameter "to" is required (e.g. "1102", "1401", "ดอกคูน", "ห้องน้ำ", "r3206").'
    });
  }

  const startNode = resolveNode(fromParam, nodesMap.get('poi_f2_main_entrance'));
  const targetResolved = resolveNode(toParam);

  if (!startNode || startNode.isSpecialType) {
    return res.status(400).json({
      success: false,
      error: `Could not resolve start location: "${fromParam}"`
    });
  }

  let route = null;
  if (targetResolved && targetResolved.isSpecialType === 'restroom') {
    route = findPath(startNode.id, null, 'restroom');
  } else if (targetResolved && targetResolved.id) {
    route = findPath(startNode.id, targetResolved.id);
  } else {
    const fallbackNode = resolveNode(toParam);
    if (fallbackNode && fallbackNode.id) {
      route = findPath(startNode.id, fallbackNode.id);
    }
  }

  if (!route) {
    return res.status(404).json({
      success: false,
      error: `No route found from "${fromParam}" to "${toParam}".`
    });
  }

  const response = buildNavigationResponse(req, route);
  res.json(response);
}

// API Routes
app.get('/api/route', handleNavigationRequest);
app.post('/api/route', handleNavigationRequest);
app.get('/api/zenbo/navigate', handleNavigationRequest);
app.post('/api/zenbo/navigate', handleNavigationRequest);

// API: Nearest Amenity
app.get('/api/nearest-amenity', (req, res) => {
  const fromParam = req.query.from || 'poi_f2_main_entrance';
  const type = req.query.type || 'restroom';

  const startNode = resolveNode(fromParam, nodesMap.get('poi_f2_main_entrance'));
  if (!startNode) {
    return res.status(400).json({ success: false, error: 'Invalid start point.' });
  }

  const route = findPath(startNode.id, null, type);
  if (!route) {
    return res.status(404).json({ success: false, error: `No nearest ${type} found.` });
  }

  const response = buildNavigationResponse(req, route);
  res.json(response);
});

// API: Raw Graph data
app.get('/api/graph', (req, res) => {
  res.json({
    success: true,
    data: graphData
  });
});

// API: Health check
app.get('/api/health', (req, res) => {
  res.json({
    status: 'healthy',
    uptime: process.uptime(),
    timestamp: new Date().toISOString()
  });
});

// Fallback to index.html for SPA routing
app.get('*', (req, res) => {
  if (req.path.startsWith('/api')) {
    return res.status(404).json({ error: 'Endpoint not found' });
  }
  res.sendFile(path.join(__dirname, 'public', 'index.html'));
});

app.listen(PORT, () => {
  console.log(`🏛️ KKUL Smart Navigation Server Running on http://localhost:${PORT}`);
});
