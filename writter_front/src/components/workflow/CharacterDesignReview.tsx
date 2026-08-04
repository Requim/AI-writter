import { CheckOutlined, EditOutlined, ReloadOutlined } from '@ant-design/icons'
import { Button, Input, Radio, Tag } from 'antd'
import { useMemo, useState } from 'react'
import type {
  CharacterDesignProposal, CharacterDesignRole, CharacterDesignSelection,
  CharacterNameCandidate, InterruptInfo, JsonValue, ResolvedCharacter,
} from '@/types/novel'
import { ReviewHeading, ReviewValue } from './ReviewPrimitives'
import { asText, characterDesignFrom } from './valueHelpers'

interface Props {
  interrupt: InterruptInfo
  onConfirm: (value?: CharacterDesignSelection) => void
  onRegenerate: () => void
}

const roleLabels: Record<string, string> = {
  protagonist: '主角', male_lead: '男主角', female_lead: '女主角',
  deuteragonist: '第二主角', antagonist: '主要对手', love_interest: '情感主角',
}

function roleLabel(role: CharacterDesignRole): string {
  return roleLabels[role.role_type] || role.role_type || '核心角色'
}

function profileText(profile: Record<string, JsonValue>, keys: string[]): string | undefined {
  for (const key of keys) {
    const value = asText(profile[key])
    if (value) return value
  }
  return undefined
}

function recommendedMap(proposal: CharacterDesignProposal): Record<string, string> {
  return Object.fromEntries(proposal.core_roles.map((role) => {
    const valid = role.name_candidates.some((item) => item.candidate_id === role.recommended_candidate_id)
    return [role.character_id, valid ? role.recommended_candidate_id : role.name_candidates[0]?.candidate_id || '']
  }))
}

function selectionValue(
  proposal: CharacterDesignProposal,
  selected: Record<string, string>,
  custom: Record<string, string>,
): CharacterDesignSelection | undefined {
  const customNames = Object.fromEntries(Object.entries(custom).map(([key, value]) => [key, value.trim()]).filter(([, value]) => value))
  const nameSelections = Object.fromEntries(proposal.core_roles.filter((role) => {
    return !customNames[role.character_id] && selected[role.character_id] !== role.recommended_candidate_id
  }).map((role) => [role.character_id, selected[role.character_id]]).filter(([, value]) => value))
  if (!Object.keys(customNames).length && !Object.keys(nameSelections).length) return undefined
  return {
    ...(Object.keys(nameSelections).length ? { name_selections: nameSelections } : {}),
    ...(Object.keys(customNames).length ? { custom_names: customNames } : {}),
  }
}

function useRoleSelections(proposal: CharacterDesignProposal) {
  const recommended = useMemo(() => recommendedMap(proposal), [proposal])
  const [selected, setSelected] = useState<Record<string, string>>(recommended)
  const [custom, setCustom] = useState<Record<string, string>>({})
  const choose = (characterId: string, candidateId: string) => {
    setSelected((current) => ({ ...current, [characterId]: candidateId }))
    setCustom((current) => ({ ...current, [characterId]: '' }))
  }
  const customize = (characterId: string, name: string) => {
    setCustom((current) => ({ ...current, [characterId]: name }))
  }
  const complete = proposal.core_roles.every((role) => selected[role.character_id] || custom[role.character_id]?.trim())
  return { selected, custom, choose, customize, complete, value: selectionValue(proposal, selected, custom) }
}

function CandidateOption({ candidate, selected }: { candidate: CharacterNameCandidate; selected: boolean }) {
  return <Radio value={candidate.candidate_id} className={`name-candidate${selected ? ' selected' : ''}`}>
    <div className="name-candidate-copy">
      <div className="candidate-heading"><strong>{candidate.name}</strong>{candidate.pinyin && <small>{candidate.pinyin}</small>}<Tag>{candidate.source_title}</Tag></div>
      <blockquote>{candidate.source_quote}</blockquote>
      <dl><div><dt>寓意</dt><dd>{candidate.meaning}</dd></div>
        {candidate.role_fit && <div><dt>人物适配</dt><dd>{candidate.role_fit}</dd></div>}
      </dl>
    </div>
  </Radio>
}

interface RoleProps {
  role: CharacterDesignRole
  selected?: string
  customName?: string
  onChoose: (candidateId: string) => void
  onCustomize: (name: string) => void
}

function RoleSection({ role, selected, customName = '', onChoose, onCustomize }: RoleProps) {
  const identity = profileText(role.profile, ['identity', '身份', 'occupation', '职业'])
  const drive = profileText(role.profile, ['external_goal', '外在目标', 'goal', '目标'])
  return <section className="character-role">
    <header><div><Tag color="green">{roleLabel(role)}</Tag><strong>{identity || '核心人物'}</strong></div>{drive && <p>{drive}</p>}</header>
    <Radio.Group value={selected} onChange={(event) => onChoose(event.target.value)} className="name-candidate-list">
      {role.name_candidates.map((candidate) => <CandidateOption key={candidate.candidate_id} candidate={candidate} selected={candidate.candidate_id === selected && !customName.trim()} />)}
    </Radio.Group>
    <div className={`custom-name${customName.trim() ? ' active' : ''}`}>
      <label htmlFor={`custom-name-${role.character_id}`}>自定义姓名</label>
      <Input id={`custom-name-${role.character_id}`} aria-label={`${roleLabel(role)}自定义姓名`} value={customName}
        onChange={(event) => onCustomize(event.target.value)} maxLength={20} allowClear prefix={<EditOutlined />} placeholder="输入后将覆盖上方候选" />
    </div>
  </section>
}

function SupportingCharacters({ characters }: { characters: ResolvedCharacter[] }) {
  if (!characters.length) return null
  return <details className="supporting-characters"><summary>配角名单 · {characters.length} 人</summary>
    <div>{characters.map((character) => <span key={character.character_id}>
      <strong>{character.name}</strong><small>{roleLabels[character.role_type] || character.role_type}</small>
    </span>)}</div>
  </details>
}

export function CharacterDesignReview({ interrupt, onConfirm, onRegenerate }: Props) {
  const proposal = characterDesignFrom(interrupt)
  if (!proposal) return null
  return <CharacterDesignForm proposal={proposal} onConfirm={onConfirm} onRegenerate={onRegenerate} />
}

function CharacterDesignForm({ proposal, onConfirm, onRegenerate }: Omit<Props, 'interrupt'> & { proposal: CharacterDesignProposal }) {
  const selection = useRoleSelections(proposal)
  return <>
    <div className="review-surface character-design-review">
      <ReviewHeading eyebrow="角色设计" title={`${proposal.core_roles.length} 名核心角色`} />
      <div className="character-role-list">{proposal.core_roles.map((role) => <RoleSection key={role.character_id}
        role={role} selected={selection.selected[role.character_id]} customName={selection.custom[role.character_id]}
        onChoose={(candidateId) => selection.choose(role.character_id, candidateId)}
        onCustomize={(name) => selection.customize(role.character_id, name)} />)}</div>
      <SupportingCharacters characters={proposal.supporting_characters || []} />
      {proposal.relationships?.length > 0 && <details><summary>人物关系</summary><ReviewValue value={proposal.relationships} /></details>}
    </div>
    <div className="interrupt-actions character-design-actions">
      <Button type="primary" icon={<CheckOutlined />} aria-label="确认角色设计" disabled={!selection.complete} onClick={() => onConfirm(selection.value)}>确认角色设计</Button>
      <Button icon={<ReloadOutlined />} aria-label="重新生成角色设计" onClick={onRegenerate}>重新生成</Button>
    </div>
  </>
}
