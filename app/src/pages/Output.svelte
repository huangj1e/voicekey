<script lang="ts">
  import { app, save } from "../lib/store.svelte";
  const s = $derived(app.s!);
  const all = $derived(s.channel === "all");
  const linux = $derived(app.info?.platform === "linux");
</script>

<h2>输出</h2>
<div class="sub">识别结果如何进入输入框。</div>
<div class="group">
  <div class="row">
    <div class="lbl">边说边上屏<small>{linux ? "Linux 在录音结束后直接输入定稿，避免快捷键修饰键影响输入" : all ? "「多渠道」模式下需先挑选结果，此项不可用" : "识别中的文字实时打到光标处，结束后按定稿修正；关闭后改为结束时一次性粘贴"}</small></div>
    <button class="sw" class:on={s.streaming && !linux} disabled={all || linux} onclick={() => save({ streaming: !s.streaming })} aria-label="边说边上屏"></button>
  </div>
  <div class="row">
    <div class="lbl">胶囊显示实时文字<small>在屏幕底部胶囊中预览识别内容</small></div>
    <button class="sw" class:on={s.liveText} onclick={() => save({ liveText: !s.liveText })} aria-label="胶囊显示实时文字"></button>
  </div>
</div>
