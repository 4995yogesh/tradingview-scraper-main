const statusDiv = document.getElementById('status');

const timeframes = ["4H", "1H", "15m", "5m", "1m"];
const canvasses = {};
const contexts = {};

timeframes.forEach(tf => {
    const cvs = document.getElementById(`canvas-${tf}`);
    canvasses[tf] = cvs;
    contexts[tf] = cvs.getContext('2d');
});

// Canvas Setup
function resizeAll() {
    timeframes.forEach(tf => {
        const cvs = canvasses[tf];
        cvs.width = cvs.parentElement.clientWidth;
        cvs.height = cvs.parentElement.clientHeight;
    });
}
window.addEventListener('resize', () => {
    resizeAll();
    if(apiData) drawAll();
});
resizeAll();

let apiData = null;

// Data Polling
async function pollData() {
    try {
        statusDiv.innerText = "Fetching...";
        const res = await fetch('/scenarios');
        if (res.ok) {
            apiData = await res.json();
            statusDiv.innerText = "Live";
            drawAll();
        } else {
            statusDiv.innerText = "Error API";
        }
    } catch (err) {
        statusDiv.innerText = "Error Connection";
    }
    setTimeout(pollData, 3000);
}
pollData();

function drawAll() {
    timeframes.forEach(tf => {
        if(apiData[tf]) {
            drawChart(contexts[tf], canvasses[tf], apiData[tf]);
        }
    });
}

function drawGrid(ctx, canvas) {
    ctx.strokeStyle = 'rgba(255, 255, 255, 0.05)';
    ctx.lineWidth = 1;
    for(let y=0; y<canvas.height; y+=40) {
        ctx.beginPath(); ctx.moveTo(0, y); ctx.lineTo(canvas.width, y); ctx.stroke();
    }
    for(let x=0; x<canvas.width; x+=40) {
        ctx.beginPath(); ctx.moveTo(x, 0); ctx.lineTo(x, canvas.height); ctx.stroke();
    }
}

// Drawing Logic per timeframe
function drawChart(ctx, canvas, scenarios) {
    // Clear
    ctx.clearRect(0, 0, canvas.width, canvas.height);
    
    // Grid
    drawGrid(ctx, canvas);
    
    if (!scenarios || scenarios.length === 0) return;
    
    // Find active scenarios
    const activeScenarios = scenarios.filter(s => s.type !== 'none');
    
    if (activeScenarios.length === 0) {
        ctx.fillStyle = '#64748b';
        ctx.font = '12px Inter';
        ctx.fillText('No active setups', 20, canvas.height - 20);
        return;
    }
    
    // Determine Price Bounds to scale Y axis
    let minPrice = Infinity;
    let maxPrice = -Infinity;
    
    activeScenarios.forEach(s => {
        if(s.sl < minPrice) minPrice = s.sl;
        if(s.sl > maxPrice) maxPrice = s.sl;
        if(s.tp_zone.low < minPrice) minPrice = s.tp_zone.low;
        if(s.tp_zone.high > maxPrice) maxPrice = s.tp_zone.high;
        if(s.entry < minPrice) minPrice = s.entry;
        if(s.entry > maxPrice) maxPrice = s.entry;
        
        s.path.forEach(p => {
            if(p[1] < minPrice) minPrice = p[1];
            if(p[1] > maxPrice) maxPrice = p[1];
        });
    });
    
    // Add margin to scale
    const priceRange = maxPrice - minPrice;
    if (priceRange === 0) return;
    
    minPrice -= priceRange * 0.2;
    maxPrice += priceRange * 0.2;

    const screenY = (price) => canvas.height - ((price - minPrice) / (maxPrice - minPrice)) * canvas.height;
    
    // Draw Scenarios
    activeScenarios.forEach((s) => {
        // Draw TP bounds
        ctx.fillStyle = 'rgba(76, 175, 80, 0.15)';
        const yTop = screenY(s.tp_zone.high);
        const yBot = screenY(s.tp_zone.low);
        ctx.fillRect(0, yTop, canvas.width, yBot - yTop);
        
        // Draw TP line
        ctx.strokeStyle = '#4caf50';
        ctx.setLineDash([5, 5]);
        ctx.lineWidth = 1;
        ctx.beginPath();
        ctx.moveTo(0, yTop);
        ctx.lineTo(canvas.width, yTop);
        ctx.stroke();
        
        // Draw SL line
        const slY = screenY(s.sl);
        ctx.strokeStyle = '#ff4d4d';
        ctx.beginPath();
        ctx.moveTo(0, slY);
        ctx.lineTo(canvas.width, slY);
        ctx.stroke();
        ctx.setLineDash([]);
        
        // Draw Label
        ctx.fillStyle = '#ffffff';
        ctx.font = '10px Inter';
        ctx.fillText(`SL`, 5, slY - 3);
        ctx.fillText(`TP`, 5, yTop - 3);
        
        // Draw Path
        if (s.path && s.path.length > 0) {
            ctx.beginPath();
            const startX = canvas.width * 0.3; // Start paths at 30% of screen width
            const spaceX = (canvas.width * 0.6) / s.path.length;
            
            ctx.moveTo(startX, screenY(s.entry));
            
            s.path.forEach((pt, i) => {
                const x = startX + (i + 1) * spaceX;
                const y = screenY(pt[1]);
                ctx.lineTo(x, y);
                
                // Draw nodes
                ctx.arc(x, y, 2, 0, Math.PI*2);
                ctx.moveTo(x, y);
            });
            
            ctx.strokeStyle = s.scenario_name === "Continuation" ? '#3b82f6' : '#f97316';
            ctx.lineWidth = 2;
            // Adds a glow
            ctx.shadowColor = ctx.strokeStyle;
            ctx.shadowBlur = 8;
            ctx.stroke();
            // Reset glow
            ctx.shadowBlur = 0;
        }
    });

    // Mock a Consolidation Box at the start of the path to show context visually
    const boxYTop = screenY(activeScenarios[0].entry + priceRange*0.05);
    const boxYBot = screenY(activeScenarios[0].entry - priceRange*0.05);
    ctx.fillStyle = 'rgba(255, 255, 255, 0.05)';
    ctx.strokeStyle = '#ffffff';
    ctx.lineWidth = 1;
    const boxStartX = canvas.width * 0.1;
    const boxWidth = canvas.width * 0.2;
    ctx.fillRect(boxStartX, boxYTop, boxWidth, boxYBot - boxYTop);
    ctx.strokeRect(boxStartX, boxYTop, boxWidth, boxYBot - boxYTop);
}
