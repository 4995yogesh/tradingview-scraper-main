import React from 'react';

const LayerController = ({ layers, onToggle }) => {
  const order = ['4H', '1H', '15m', '5m', '1m'];
  
  return (
    <div className="floating-panel">
      <div className="panel-title">Layers</div>
      {order.map(tf => (
        <div 
          key={tf}
          className={`layer-toggle ${layers[tf] ? 'active' : ''}`}
          onClick={() => onToggle(tf)}
        >
          <span>{tf}</span>
          <div className="indicator" />
        </div>
      ))}
    </div>
  );
};

export default LayerController;
