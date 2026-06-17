export type Visibility = "visible" | "teaser";

export interface SectionOut {
  id: string;
  order: number;
  visibility: Visibility;
  content: string | null;
  rule_type: string;
  rule_label: string;
  teaser_text: string | null;
}
export interface NoteOut {
  id: string;
  author_id: string;
  title: string;
  lng: number | null;
  lat: number | null;
  sections: SectionOut[];
}
export interface MapOut {
  id: string;
  name: string;
  lng: number;
  lat: number;
  zoom: number;
}
export interface Viewer {
  id: string;
  display_name: string;
  reputation: number;
}

export interface Group { id: string; name: string; }

export interface SectionInput {
  order: number;
  content: string;
  rule_type: string;
  rule_params: Record<string, unknown>;
  teaser: boolean;
  teaser_text: string;
}
export interface NoteInput { title: string; lng: number; lat: number; sections: SectionInput[]; }
export interface NoteUpdateInput extends NoteInput { version: number; }

export type SectionEdit = SectionInput;
export interface NoteEdit {
  id: string;
  title: string;
  lng: number | null;
  lat: number | null;
  version: number;
  sections: SectionEdit[];
}
