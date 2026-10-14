import { cn } from "@/lib/utils";

const LABEL_COLORS: Record<string, { bg: string; text: string; border: string }> = {
  // Databases
  "Database": { bg: "bg-blue-500/5", text: "text-blue-500/60", border: "border-blue-500/20" },
  "Vector": { bg: "bg-indigo-500/5", text: "text-indigo-500/60", border: "border-indigo-500/20" },
  "Graph": { bg: "bg-violet-500/5", text: "text-violet-500/60", border: "border-violet-500/20" },

  // Communication tools
  "Communication": { bg: "bg-purple-400/5", text: "text-purple-500/60", border: "border-purple-500/20" },
  "Email": { bg: "bg-pink-500/5", text: "text-pink-500/60", border: "border-pink-500/20" },
  "Team Collaboration": { bg: "bg-rose-500/5", text: "text-rose-500/60", border: "border-rose-500/20" },

  // Task and productivity
  "Productivity": { bg: "bg-green-500/5", text: "text-green-600/60", border: "border-green-500/20" },
  "Calendar": { bg: "bg-emerald-500/5", text: "text-emerald-500/60", border: "border-emerald-500/20" },
  "Task Management": { bg: "bg-lime-500/5", text: "text-lime-600/60", border: "border-lime-500/20" },
  "Project Management": { bg: "bg-teal-500/5", text: "text-teal-500/70", border: "border-teal-500/20" },
  "Issue Tracking": { bg: "bg-cyan-500/5", text: "text-cyan-600/60", border: "border-cyan-500/20" },

  // Knowledge and documents
  "Knowledge Base": { bg: "bg-amber-500/5", text: "text-amber-600/60", border: "border-amber-500/20" },
  "Documentation": { bg: "bg-yellow-500/5", text: "text-yellow-600/60", border: "border-yellow-500/20" },
  "File Storage": { bg: "bg-orange-500/5", text: "text-orange-500/60", border: "border-orange-500/20" },

  // Business tools
  "Customer Service": { bg: "bg-fuchsia-500/5", text: "text-fuchsia-500/60", border: "border-fuchsia-500/20" },
  "Support": { bg: "bg-sky-500/5", text: "text-sky-500/60", border: "border-sky-500/20" },
  "CRM": { bg: "bg-cyan-500/5", text: "text-cyan-600/60", border: "border-cyan-500/20" },
  "Marketing": { bg: "bg-amber-500/5", text: "text-amber-600/60", border: "border-amber-500/20" },
};

interface LabelBadgeProps {
  label: string;
  className?: string;
}

export function LabelBadge({ label, className }: LabelBadgeProps) {
  const colors = LABEL_COLORS[label] || {
    bg: "bg-gray-500/5",
    text: "text-gray-500/60",
    border: "border-gray-500/20"
  };

  return (
    <span
      className={cn(
        "inline-flex items-center px-2.5 py-0.5 rounded-full text-xs font-medium",
        "border transition-colors duration-200 ease-in-out",
        colors.bg,
        colors.text,
        colors.border,
        className
      )}
    >
      {label}
    </span>
  );
}
