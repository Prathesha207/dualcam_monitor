import React from 'react';
import { BookOpen, Camera, Sparkles, SlidersHorizontal, Disc } from 'lucide-react';
import { Modal, Button } from './ui';

interface HelpModalProps {
  isOpen: boolean;
  onClose: () => void;
}

export const HelpModal: React.FC<HelpModalProps> = ({ isOpen, onClose }) => {
  return (
    <Modal
      isOpen={isOpen}
      onClose={onClose}
      maxWidth="xl"
      icon={<BookOpen className="w-4 h-4 text-[var(--accent-pond)]" />}
      title="Vision Monitor • User Guide"
      description="DepthAI Camera Streaming, Hardware Controls & Video Recording"
      footer={
        <Button
          variant="primary"
          size="md"
          onClick={() => {
            onClose();
          }}
        >
          Got it!
        </Button>
      }
    >
      <div className="space-y-4 text-xs leading-relaxed text-[var(--text-primary)]">
        
        {/* Section 1: Overview */}
        <div className="p-3.5 rounded-2xl bg-[var(--accent-pond-subtle)] border border-[var(--border-color)]">
          <h3 className="font-bold text-sm text-[var(--accent-pond)] mb-1.5 flex items-center gap-1.5">
            <Camera className="w-4 h-4 text-[var(--accent-pond)]" />
            DepthAI OAK-D System Overview
          </h3>
          <p className="text-[var(--text-secondary)]">
            Vision Monitor connects directly to Luxonis DepthAI cameras (USB &amp; PoE). It provides an ultra-low latency MJPEG video stream, real-time sensor tuning (exposure, gain, focus, brightness, contrast), instantaneous high-res snapshots, and direct-to-disk video recording.
          </p>
        </div>

        {/* Section 2: Core Features */}
        <div>
          <h3 className="font-bold text-sm text-[var(--text-primary)] mb-2 flex items-center gap-1.5">
            <Sparkles className="w-4 h-4 text-[var(--accent-tube)]" />
            Key Features
          </h3>
          <div className="grid grid-cols-1 sm:grid-cols-2 gap-2 text-xs">
            <div className="p-2.5 rounded-xl bg-[var(--bg-card-subtle)] border border-[var(--border-color)]">
              <span className="font-bold text-[var(--accent-pond)] flex items-center gap-1">
                <SlidersHorizontal className="w-3.5 h-3.5" /> Live Sensor Adjustments
              </span>
              <p className="text-[11px] text-[var(--text-secondary)] mt-0.5">
                Adjust exposure time, ISO gain, manual focus distance, brightness, and contrast in real time. Changes are saved directly to the database.
              </p>
            </div>

            <div className="p-2.5 rounded-xl bg-[var(--bg-card-subtle)] border border-[var(--border-color)]">
              <span className="font-bold text-[var(--accent-pond)] flex items-center gap-1">
                <Disc className="w-3.5 h-3.5 text-rose-500" /> Lossless Video Recording
              </span>
              <p className="text-[11px] text-[var(--text-secondary)] mt-0.5">
                Record camera video directly to your desktop or custom folder in MP4 or AVI format with a single click.
              </p>
            </div>
          </div>
        </div>

        {/* Section 3: Keyboard Shortcuts */}
        <div>
          <h3 className="font-bold text-xs uppercase tracking-wider text-[var(--text-secondary)] mb-1.5">
            Keyboard Shortcuts
          </h3>
          <div className="grid grid-cols-2 gap-2 text-xs font-mono">
            <div className="flex justify-between p-2 rounded-lg bg-[var(--bg-card-subtle)] border border-[var(--border-color)]">
              <span>Start / Stop Stream:</span>
              <kbd className="px-1.5 py-0.5 bg-[var(--bg-card)] text-[var(--text-primary)] border border-[var(--border-color)] rounded-md font-bold shadow-xs">Space</kbd>
            </div>
            <div className="flex justify-between p-2 rounded-lg bg-[var(--bg-card-subtle)] border border-[var(--border-color)]">
              <span>Toggle Fullscreen:</span>
              <kbd className="px-1.5 py-0.5 bg-[var(--bg-card)] text-[var(--text-primary)] border border-[var(--border-color)] rounded-md font-bold shadow-xs">F</kbd>
            </div>
            <div className="flex justify-between p-2 rounded-lg bg-[var(--bg-card-subtle)] border border-[var(--border-color)]">
              <span>Capture Snapshot:</span>
              <kbd className="px-1.5 py-0.5 bg-[var(--bg-card)] text-[var(--text-primary)] border border-[var(--border-color)] rounded-md font-bold shadow-xs">S</kbd>
            </div>
            <div className="flex justify-between p-2 rounded-lg bg-[var(--bg-card-subtle)] border border-[var(--border-color)]">
              <span>Toggle Adjustments:</span>
              <kbd className="px-1.5 py-0.5 bg-[var(--bg-card)] text-[var(--text-primary)] border border-[var(--border-color)] rounded-md font-bold shadow-xs">C</kbd>
            </div>
          </div>
        </div>
      </div>
    </Modal>
  );
};
