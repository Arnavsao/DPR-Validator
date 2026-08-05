'use client';
import { useState, useEffect } from 'react';
import Link from 'next/link';
import { usePathname } from 'next/navigation';
import {
  LayoutDashboard, Upload, GitCompare,
  Train, Sun, Moon,
} from 'lucide-react';

const navLinks = [
  { href: '/',        label: 'Dashboard',  icon: LayoutDashboard },
  { href: '/upload',  label: 'Upload DPR', icon: Upload },
  { href: '/compare', label: 'Compare',    icon: GitCompare },
];

export default function Sidebar() {
  const path = usePathname();
  const [theme, setTheme] = useState<'dark' | 'light'>('dark');
  const [mounted, setMounted] = useState(false);

  useEffect(() => {
    setMounted(true);
    const saved = localStorage.getItem('theme') as 'dark' | 'light' | null;
    const initial = saved || (window.matchMedia('(prefers-color-scheme: light)').matches ? 'light' : 'dark');
    setTheme(initial);
    document.documentElement.setAttribute('data-theme', initial);
  }, []);

  const toggleTheme = () => {
    const next = theme === 'dark' ? 'light' : 'dark';
    setTheme(next);
    localStorage.setItem('theme', next);
    document.documentElement.setAttribute('data-theme', next);
  };

  return (
    <aside style={{
      width: 220,
      minHeight: '100vh',
      background: 'var(--sidebar-bg)',
      borderRight: '1px solid var(--border)',
      display: 'flex',
      flexDirection: 'column',
      padding: '24px 12px',
      flexShrink: 0,
      position: 'sticky',
      top: 0,
      alignSelf: 'flex-start',
      height: '100vh',
      transition: 'background-color 0.25s ease, border-color 0.25s ease',
    }}>
      {/* Logo */}
      <div style={{ padding: '0 8px 28px' }}>
        <div style={{ display: 'flex', alignItems: 'center', gap: 10, marginBottom: 4 }}>
          <div style={{
            width: 36, height: 36, borderRadius: 10,
            background: 'linear-gradient(135deg, var(--railway-blue), var(--railway-blue-light))',
            display: 'flex', alignItems: 'center', justifyContent: 'center',
            boxShadow: '0 4px 12px rgba(10,61,145,0.3)',
          }}>
            <Train size={18} color="white" />
          </div>
          <div>
            <div style={{ fontWeight: 700, fontSize: 14, color: 'var(--text-primary)', lineHeight: 1.2 }}>
              DPR Validator
            </div>
            <div style={{ fontSize: 10, color: 'var(--text-muted)', letterSpacing: '0.06em', textTransform: 'uppercase' }}>
              Railway Edition
            </div>
          </div>
        </div>
      </div>

      {/* Nav */}
      <nav style={{ flex: 1, display: 'flex', flexDirection: 'column', gap: 4 }}>
        <div style={{ fontSize: 10, fontWeight: 600, color: 'var(--text-muted)', letterSpacing: '0.08em', textTransform: 'uppercase', padding: '0 8px', marginBottom: 6 }}>
          Navigation
        </div>
        {navLinks.map(({ href, label, icon: Icon }) => {
          const active = path === href || (href !== '/' && path.startsWith(href));
          return (
            <Link key={href} href={href} className={`nav-item ${active ? 'active' : ''}`}>
              <Icon size={16} />
              {label}
            </Link>
          );
        })}
      </nav>

      {/* Theme Toggle & Footer */}
      <div style={{ padding: '16px 8px 0', borderTop: '1px solid var(--border)', display: 'flex', flexDirection: 'column', gap: 12 }}>
        {/* Theme Toggle Button */}
        <button
          onClick={toggleTheme}
          style={{
            display: 'flex',
            alignItems: 'center',
            justifyContent: 'space-between',
            width: '100%',
            padding: '8px 12px',
            borderRadius: 8,
            border: '1px solid var(--border)',
            background: 'var(--surface-2)',
            color: 'var(--text-primary)',
            fontSize: 12,
            fontWeight: 500,
            cursor: 'pointer',
            transition: 'all 0.2s ease',
          }}
          title={`Switch to ${theme === 'dark' ? 'Light' : 'Dark'} mode`}
        >
          <span style={{ display: 'flex', alignItems: 'center', gap: 8 }}>
            {mounted && theme === 'light' ? (
              <Sun size={15} style={{ color: '#D97706' }} />
            ) : (
              <Moon size={15} style={{ color: '#6BA3FF' }} />
            )}
            <span>{mounted && theme === 'light' ? 'Light Mode' : 'Dark Mode'}</span>
          </span>
          <span style={{ fontSize: 10, padding: '2px 6px', borderRadius: 4, background: 'var(--surface-3)', color: 'var(--text-muted)' }}>
            Toggle
          </span>
        </button>

        <div style={{ fontSize: 11, color: 'var(--text-muted)', lineHeight: 1.5 }}>
          <div style={{ fontWeight: 600, color: 'var(--text-secondary)', marginBottom: 2 }}>DPR Validator v2.0</div>
          RAG-powered validation.<br />
          Grounded & zero hallucination.
        </div>
      </div>
    </aside>
  );
}
