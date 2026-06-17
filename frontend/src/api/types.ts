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
