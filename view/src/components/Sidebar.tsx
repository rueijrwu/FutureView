import React from 'react';
import { NavLink } from 'react-router-dom';
import './Sidebar.css';

const Sidebar: React.FC = () => {
  return (
    <nav className="sidebar" aria-label="Main navigation">
      <ul>
        <li><NavLink to="/" end>Home</NavLink></li>
        <li><NavLink to="/portfolio">Portfolio</NavLink></li>
        <li><NavLink to="/watchlist">Watchlist</NavLink></li>
        <li><NavLink to="/backtest">Backtest</NavLink></li>
        <li><NavLink to="/settings">Settings</NavLink></li>
      </ul>
    </nav>
  );
};

export default Sidebar;
