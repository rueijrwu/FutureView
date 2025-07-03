import React from 'react';
import Sidebar from '../components/Sidebar';
import { Outlet } from 'react-router-dom';
import './Layout.css';

const Layout: React.FC = () => {
  React.useEffect(() => {
    document.body.classList.add('dark-theme');
    return () => document.body.classList.remove('dark-theme');
  }, []);
  return (
    <div className="app-layout">
      <Sidebar />
      <main className="main-content" tabIndex={-1} id="main-content">
        <Outlet />
      </main>
    </div>
  );
};

export default Layout;
