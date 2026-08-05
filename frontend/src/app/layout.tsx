import type { Metadata } from 'next';
import './globals.css';
import Sidebar from '@/components/Sidebar';
import QueryProvider from '@/components/QueryProvider';

export const metadata: Metadata = {
  title: 'DPR Validator — Railway Detailed Project Report Validation',
  description:
    'Deterministic Railway DPR validation engine. Parse, validate, compare, and score Detailed Project Reports against the Railway format specification.',
};

export default function RootLayout({ children }: { children: React.ReactNode }) {
  return (
    <html lang="en" suppressHydrationWarning>
      <body className="gradient-bg" style={{ display: 'flex', minHeight: '100vh' }} suppressHydrationWarning>
        <QueryProvider>
          <Sidebar />
          <main style={{ flex: 1, overflowY: 'auto', padding: '32px 36px' }}>
            {children}
          </main>
        </QueryProvider>
      </body>
    </html>
  );
}
