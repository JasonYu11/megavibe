import { Wand2, Wrench } from "lucide-react";
import { useState, useEffect, useRef } from "react";

interface SkillInfo {
  name: string;
  description: string;
  run_as: string;
}

interface SkillPickerProps {
  skills: SkillInfo[];
  onSelect: (skillName: string) => void;
  onClose: () => void;
}

export function SkillPicker({ skills, onSelect, onClose }: SkillPickerProps) {
  const [query, setQuery] = useState("");
  const inputRef = useRef<HTMLInputElement>(null);

  useEffect(() => {
    inputRef.current?.focus();
  }, []);

  useEffect(() => {
    const handler = (e: KeyboardEvent) => {
      if (e.key === "Escape") onClose();
    };
    window.addEventListener("keydown", handler);
    return () => window.removeEventListener("keydown", handler);
  }, [onClose]);

  const filtered = query
    ? skills.filter((s) => s.name.includes(query.toLowerCase()) || s.description.includes(query))
    : skills;

  return (
    <div className="skillPicker" onClick={(e) => e.stopPropagation()}>
      <div className="skillPicker__search">
        <input
          ref={inputRef}
          type="text"
          placeholder="搜索 skill..."
          value={query}
          onChange={(e) => setQuery(e.target.value)}
        />
      </div>
      <div className="skillPicker__list">
        {filtered.map((skill) => (
          <button
            key={skill.name}
            className="skillPicker__item"
            onClick={() => onSelect(skill.name)}
          >
            <span className="skillPicker__itemIcon">
              {skill.run_as === "subagent" ? <Wand2 size={14} /> : <Wrench size={14} />}
            </span>
            <div className="skillPicker__itemMeta">
              <span className="skillPicker__itemName">{skill.name}</span>
              <span className="skillPicker__itemDesc">{skill.description}</span>
            </div>
            <span className="skillPicker__itemTag">{skill.run_as}</span>
          </button>
        ))}
        {filtered.length === 0 && (
          <div className="skillPicker__empty">无匹配 skill</div>
        )}
      </div>
    </div>
  );
}
