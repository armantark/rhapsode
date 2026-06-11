// Friendly aliases over the generated contract types. Regenerate the source
// of truth with: npm run generate:client
import type { components } from './schema';

export type Health = components['schemas']['HealthRead'];
export type LanguageProfile = components['schemas']['LanguageProfileRead'];
export type Passage = components['schemas']['PassageRead'];
export type PassageDetail = components['schemas']['PassageDetail'];
export type PassageInput = components['schemas']['PassageInput'];
export type Revision = components['schemas']['RevisionRead'];
export type RevisionInput = components['schemas']['RevisionInput'];
export type Segment = components['schemas']['SegmentRead'];
export type SegmentInput = components['schemas']['SegmentInput'];
export type Annotation = components['schemas']['AnnotationRead'];
export type AnnotationInput = components['schemas']['AnnotationInput'];
export type AnnotationCreate = components['schemas']['AnnotationCreate'];
export type Media = components['schemas']['MediaRead'];
export type PracticeSession = components['schemas']['SessionRead'];
// openapi-typescript marks fields with literal defaults as required
// (defaultNonNullable), but due_only genuinely is optional on the wire —
// the backend defaults it to false.
export type SessionCreate = Omit<components['schemas']['SessionCreate'], 'due_only'> & {
	due_only?: boolean;
};
export type PracticeItem = components['schemas']['PracticeItemRead'];
export type PracticeMode = components['schemas']['PracticeMode'];
// Same defaultNonNullable quirk as SessionCreate.due_only: `revealed` carries
// a literal default and is optional on the wire.
export type AttemptCreate = Omit<components['schemas']['AttemptCreate'], 'revealed'> & {
	revealed?: boolean;
};
export type CuePoint = components['schemas']['CuePoint'];
export type PersonalNote = components['schemas']['PersonalNoteRead'];
export type Collection = components['schemas']['CollectionRead'];
export type CollectionMember = components['schemas']['CollectionMemberRead'];
export type CollectionRollup = components['schemas']['CollectionRollup'];
export type CollectionCreate = components['schemas']['CollectionCreate'];
export type AttemptResult = components['schemas']['AttemptResult'];
export type AttemptRating = components['schemas']['AttemptRating'];
export type ReviewState = components['schemas']['ReviewStateRead'];
export type WeakLink = components['schemas']['WeakLinkRead'];
export type Setting = components['schemas']['SettingRead'];
export type PrepSuggestResult = components['schemas']['PrepSuggestResult'];

export type MediaCategory = 'reference' | 'saved_best';

export const PRACTICE_MODES: PracticeMode[] = [
	'shadowing',
	'progressive_fading',
	'forward_chaining',
	'backward_chaining',
	'cue_recall',
	'random_start',
	'weak_link',
	'full_passage'
];

export const ATTEMPT_RATINGS: AttemptRating[] = ['clean', 'hesitant', 'incorrect', 'revealed'];
