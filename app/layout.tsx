import type { Metadata } from 'next';
import './globals.css';

export const metadata: Metadata = {
  metadataBase: new URL('https://swarmroute-sih26123.su6u.chatgpt.site'),
  title: 'SwarmRoute — SIH26123 Research & Solution',
  description: 'A research-backed distributed edge coordination architecture for warehouse AMRs, with an interactive failure-mode simulator and hackathon build plan.',
  openGraph: {
    title: 'SwarmRoute — Edge-AI Fleet Coordination',
    description: 'Research, architecture, failure simulator and build plan for SIH26123.',
    images: [{ url: '/og.png', width: 1732, height: 908, alt: 'SwarmRoute edge-AI fleet coordination' }],
  },
  twitter: {
    card: 'summary_large_image',
    title: 'SwarmRoute — Edge-AI Fleet Coordination',
    description: 'Research, architecture, failure simulator and build plan for SIH26123.',
    images: ['/og.png'],
  },
};

export default function RootLayout({ children }: Readonly<{ children: React.ReactNode }>) {
  return (
    <html lang="en">
      <body>{children}</body>
    </html>
  );
}
