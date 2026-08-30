import {
  Activity,
  AlertCircle,
  BarChart3,
  BookOpen,
  CalendarDays,
  CheckCircle2,
  Clock3,
  FileQuestion,
  Gauge,
  Layers3,
  MessageCircleQuestion,
  ShieldCheck,
  TrendingUp,
  Users,
} from "lucide-react";

import type {
  TeacherDistribution,
  TeacherOverview,
  TeacherRoleDistribution,
  TeacherStudentActivity,
} from "@/shared/types";

const ROLE_LABELS: Record<string, string> = {
  guest: "游客",
  student: "学生",
  teacher: "教师",
  developer: "开发者",
  admin: "管理员",
  unassigned: "未关联角色",
};

const formatNumber = (value: number) => Number.isInteger(value) ? String(value) : value.toFixed(2);
const formatPercent = (value: number) => `${formatNumber(value)}%`;
const roleLabel = (code: string) => ROLE_LABELS[code] ?? code;

function MetricCard({
  icon: Icon,
  label,
  value,
  detail,
  tone = "purple",
}: {
  icon: typeof Activity;
  label: string;
  value: string;
  detail: string;
  tone?: "purple" | "blue" | "green" | "orange";
}) {
  return (
    <article className={`teacher-question-metric ${tone}`}>
      <div className="teacher-question-metric-icon"><Icon size={17} /></div>
      <div><span>{label}</span><strong>{value}</strong><small>{detail}</small></div>
    </article>
  );
}

function DistributionPanel({
  title,
  description,
  items,
  tone = "purple",
}: {
  title: string;
  description: string;
  items: TeacherDistribution[];
  tone?: "purple" | "blue" | "green";
}) {
  return (
    <section className="teacher-panel teacher-question-panel">
      <header><div><h2>{title}</h2><p>{description}</p></div><BarChart3 size={17} /></header>
      {items.length ? (
        <div className="teacher-question-distribution">
          {items.map((item) => (
            <article key={item.name}>
              <div><strong>{item.name}</strong><span>{item.count} 个问题 · {formatPercent(item.percentage)}</span></div>
              <i><b className={tone} style={{ width: `${Math.min(100, item.percentage)}%` }} /></i>
            </article>
          ))}
        </div>
      ) : <p className="teacher-empty-inline">暂无分布数据</p>}
    </section>
  );
}

function DailyQuestions({ data }: { data: TeacherOverview }) {
  const max = Math.max(1, ...data.daily_questions.map((item) => item.count));
  return (
    <section className="teacher-panel teacher-question-panel teacher-question-trend-panel">
      <header><div><h2>每日问题量</h2><p>按天查看近 {data.period_days} 天的问题变化，包含所有有记录的日期</p></div><CalendarDays size={17} /></header>
      {data.daily_questions.length ? (
        <div className="teacher-question-daily-chart" role="img" aria-label="每日问题量柱状图">
          {data.daily_questions.map((item) => (
            <div className="teacher-question-daily-bar" key={item.date} title={`${item.date}：${item.count} 个问题`}>
              <small>{item.count}</small><span style={{ height: `${Math.max(4, Math.round(item.count / max * 100))}%` }} /><label>{item.date.slice(5)}</label>
            </div>
          ))}
        </div>
      ) : <p className="teacher-empty-inline">暂无趋势数据</p>}
    </section>
  );
}

function HourlyQuestions({ data }: { data: TeacherOverview }) {
  const max = Math.max(1, ...data.hourly_questions.map((item) => item.count));
  return (
    <section className="teacher-panel teacher-question-panel">
      <header><div><h2>小时分布</h2><p>识别学生最集中提问的时间段</p></div><Clock3 size={17} /></header>
      {data.hourly_questions.length ? (
        <div className="teacher-question-hour-grid">
          {data.hourly_questions.map((item) => (
            <div key={item.hour} title={`${item.label}：${item.count} 个问题`} aria-label={`${item.label} ${item.count} 个问题`}>
              <span style={{ height: `${Math.max(5, Math.round(item.count / max * 100))}%` }} />
              <small>{item.label.slice(0, 2)}</small>
            </div>
          ))}
        </div>
      ) : <p className="teacher-empty-inline">暂无时间数据</p>}
    </section>
  );
}

function WeekdayQuestions({ data }: { data: TeacherOverview }) {
  const max = Math.max(1, ...data.weekday_questions.map((item) => item.count));
  return (
    <section className="teacher-panel teacher-question-panel">
      <header><div><h2>星期分布</h2><p>比较一周内的提问活跃度</p></div><TrendingUp size={17} /></header>
      {data.weekday_questions.length ? (
        <div className="teacher-question-weekday-list">
          {data.weekday_questions.map((item) => (
            <div key={item.weekday}><span>{item.label}</span><i><b style={{ width: `${Math.min(100, item.count / max * 100)}%` }} /></i><strong>{item.count}</strong></div>
          ))}
        </div>
      ) : <p className="teacher-empty-inline">暂无星期数据</p>}
    </section>
  );
}

function RoleDistribution({ items }: { items: TeacherRoleDistribution[] }) {
  return (
    <section className="teacher-panel teacher-question-panel">
      <header><div><h2>RBAC 角色分布</h2><p>按学生账号当前角色汇总问题量；兼任多个角色的账号会分别计入</p></div><ShieldCheck size={17} /></header>
      {items.length ? (
        <div className="teacher-question-role-list">
          {items.map((item) => (
            <article key={item.code}>
              <div className="teacher-question-role-heading"><strong>{item.name}</strong><span>{item.students} 名学生账号</span></div>
              <div className="teacher-question-role-meta"><span>{item.questions} 个问题</span><b>{formatPercent(item.question_percentage)}</b></div>
              <i><b style={{ width: `${Math.min(100, item.question_percentage)}%` }} /></i>
            </article>
          ))}
        </div>
      ) : <p className="teacher-empty-inline">暂无 RBAC 角色数据</p>}
    </section>
  );
}

function StudentActivity({ items }: { items: TeacherStudentActivity[] }) {
  return (
    <section className="teacher-panel teacher-question-panel teacher-question-activity-panel">
      <header><div><h2>学生参与度</h2><p>按问题量排序，帮助老师快速识别活跃账号、持续提问账号和异常账号</p></div><Users size={17} /></header>
      {items.length ? (
        <div className="teacher-question-activity-table">
          <table>
            <thead><tr><th>学生</th><th>RBAC 角色</th><th>问题量</th><th>会话</th><th>活跃天数</th><th>异常问题</th><th>最近活跃</th><th>主要主题</th></tr></thead>
            <tbody>{items.map((item) => (
              <tr key={item.user_id}>
                <td><strong>{item.display_name}</strong>{item.username && <small>@{item.username}</small>}</td>
                <td><div className="teacher-question-role-badges">{item.role_codes.length ? item.role_codes.map((code) => <span key={code} className={code === "student" ? "student" : ""}>{roleLabel(code)}</span>) : <span>未关联角色</span>}</div></td>
                <td><strong>{item.questions}</strong><small>每会话 {formatNumber(item.questions_per_session)}</small></td>
                <td>{item.sessions}</td>
                <td>{item.active_days}</td>
                <td className={item.error_questions ? "is-warning" : ""}><strong>{item.error_questions}</strong><small>{formatPercent(item.error_rate)}</small></td>
                <td>{item.last_active ?? "—"}</td>
                <td>{item.top_topic}</td>
              </tr>
            ))}</tbody>
          </table>
        </div>
      ) : <p className="teacher-empty-state">暂无学生问题记录。</p>}
    </section>
  );
}

export function StudentQuestionsPage({ data }: { data: TeacherOverview }) {
  const { summary } = data;
  return (
    <div className="teacher-stack teacher-question-stack">
      <section className="teacher-page-summary teacher-question-hero">
        <div><span className="teacher-eyebrow">QUESTION INSIGHT · RBAC CLASSROOM</span><h2>学生问题全景</h2><p>从问题量、学习上下文、时间分布和学生角色四个维度，快速判断班级当前的学习信号。</p></div>
        <MessageCircleQuestion size={46} />
      </section>

      <section className="teacher-question-metrics" aria-label="问题量概览">
        <MetricCard icon={MessageCircleQuestion} label="问题总数" value={formatNumber(summary.questions)} detail={`近 ${data.period_days} 天`} />
        <MetricCard icon={Users} label="提问学生" value={formatNumber(summary.students)} detail={`${summary.student_role_users} 个账号具备学生角色`} tone="blue" />
        <MetricCard icon={Layers3} label="活跃会话" value={formatNumber(summary.sessions)} detail={`平均每会话 ${formatNumber(summary.questions_per_session)} 个问题`} tone="blue" />
        <MetricCard icon={Gauge} label="人均问题" value={formatNumber(summary.questions_per_student)} detail="按有提问记录的学生计算" tone="green" />
        <MetricCard icon={CalendarDays} label="活跃天数" value={formatNumber(summary.active_days)} detail={`占统计周期 ${formatPercent(data.period_days ? summary.active_days / data.period_days * 100 : 0)}`} tone="green" />
        <MetricCard icon={BookOpen} label="上下文完整度" value={formatPercent(summary.context_coverage_rate)} detail={`${summary.contextualized_questions} 个问题已关联主题`} tone="purple" />
        <MetricCard icon={AlertCircle} label="异常问题" value={formatNumber(summary.error_questions)} detail={`异常率 ${formatPercent(summary.error_rate)}`} tone="orange" />
        <MetricCard icon={CheckCircle2} label="练习完成" value={formatNumber(summary.exercises)} detail={`通过率 ${summary.exercises ? formatPercent(summary.exercise_pass_rate) : "—"}`} tone="green" />
      </section>

      <section className="teacher-question-signal-strip">
        <div><Activity size={16} /><span>问题高峰</span><strong>{data.peak_day ? `${data.peak_day.date} · ${data.peak_day.count} 个` : "暂无"}</strong></div>
        <div><Clock3 size={16} /><span>高峰时段</span><strong>{data.peak_hour ? `${data.peak_hour.label} · ${data.peak_hour.count} 个` : "暂无"}</strong></div>
        <div><FileQuestion size={16} /><span>问题类型</span><strong>{data.mode_distribution[0] ? `${data.mode_distribution[0].name}占比 ${formatPercent(data.mode_distribution[0].percentage)}` : "暂无"}</strong></div>
        <div><BookOpen size={16} /><span>最热主题</span><strong>{data.topic_distribution[0] ? `${data.topic_distribution[0].name} · ${data.topic_distribution[0].count} 个` : "暂无"}</strong></div>
      </section>

      <div className="teacher-question-grid teacher-question-grid-three">
        <DistributionPanel title="主题分布" description="按学习上下文归类" items={data.topic_distribution} />
        <DistributionPanel title="难度分布" description="按问题发生时的学习难度" items={data.difficulty_distribution} tone="blue" />
        <DistributionPanel title="模式分布" description="讲解、引导、练习和复习" items={data.mode_distribution} tone="green" />
      </div>

      <div className="teacher-question-grid teacher-question-grid-trend">
        <DailyQuestions data={data} />
        <HourlyQuestions data={data} />
      </div>
      <div className="teacher-question-grid teacher-question-grid-two">
        <WeekdayQuestions data={data} />
        <RoleDistribution items={data.role_distribution} />
      </div>
      <StudentActivity items={data.student_activity} />
    </div>
  );
}

