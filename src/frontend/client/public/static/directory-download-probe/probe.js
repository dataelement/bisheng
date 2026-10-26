/* Throwaway browser capability probe; no application APIs or user files. */
(() => {
  document.getElementById('back').addEventListener('click', () => window.history.back());
  const button = document.getElementById('run');
  const status = document.getElementById('status');
  const output = document.getElementById('report');
  const report = {
    probeVersion: 1,
    environment: {
      userAgent: navigator.userAgent,
      origin: location.origin,
      secureContext: window.isSecureContext,
      embedded: window.top !== window.self,
      directoryPicker: typeof window.showDirectoryPicker === 'function',
    },
    result: 'not_run',
    steps: [],
  };
  const render = () => { output.value = JSON.stringify(report, null, 2); };
  const log = (step, detail) => {
    report.steps.push({ time: new Date().toISOString(), step, detail });
    render();
  };
  status.textContent = report.environment.directoryPicker
    ? '检测到目录选择接口；仍需点击按钮完成实际写入验证。'
    : '当前页面未提供目录选择接口，不能通过此网页直接保存本地文件夹。请保留环境信息反馈。';
  render();

  button.addEventListener('click', async () => {
    report.steps = [];
    report.result = 'running';
    delete report.error;
    delete report.directory;
    delete report.expectedFiles;
    report.startedAt = new Date().toISOString();
    report.userActivation = navigator.userActivation?.isActive ?? null;
    button.disabled = true;
    let stage = 'preflight';
    try {
      if (!window.isSecureContext) {
        report.result = 'insecure_context';
        status.textContent = '当前不是安全上下文；请使用浏览器认可的 HTTPS，并确保外层嵌套页面也满足要求，再验证。';
        return;
      }
      if (typeof window.showDirectoryPicker !== 'function') {
        report.result = 'unsupported';
        status.textContent = '此容器未提供目录选择接口；此方案不可用。';
        return;
      }
      stage = 'picker';
      // Invoke directly in the click handler, before any asynchronous work.
      const parent = await window.showDirectoryPicker({ mode: 'readwrite' });
      log('picker_ok', '用户选择了目录');
      stage = 'create_directory';
      const suffix = Math.random().toString(36).slice(2, 10);
      const directoryName = `bisheng-download-probe-${Date.now()}-${suffix}`;
      const directory = await parent.getDirectoryHandle(directoryName, { create: true });
      report.directory = directoryName;
      log('directory_created', directoryName);
      const child = await directory.getDirectoryHandle('子文件夹', { create: true });
      await directory.getDirectoryHandle('空目录', { create: true });
      const fixtures = [
        { directory, name: '说明.txt', path: '说明.txt', text: '毕昇目录下载测试\n中文名称与 UTF-8 内容校验。\n' },
        { directory: child, name: 'sample.txt', path: '子文件夹/sample.txt', text: 'Nested file download probe.\n' },
      ];
      report.expectedFiles = fixtures.map((file) => file.path);
      for (const fixture of fixtures) {
        stage = `write:${fixture.path}`;
        const handle = await fixture.directory.getFileHandle(fixture.name, { create: true });
        const writer = await handle.createWritable();
        try {
          await writer.write(new Blob([fixture.text], { type: 'text/plain;charset=utf-8' }));
          await writer.close();
        } catch (error) {
          try { await writer.abort(); } catch { /* Preserve the original error. */ }
          throw error;
        }
        stage = `verify:${fixture.path}`;
        if (await (await handle.getFile()).text() !== fixture.text) {
          throw new Error(`Content mismatch: ${fixture.path}`);
        }
        log('file_write_read_verified', fixture.path);
      }
      report.result = 'write_read_passed';
      status.textContent = `写入和读回校验通过。\n请在系统文件管理器确认目录 ${directoryName} 及其中两个文件、子文件夹和空目录均存在。\n这只验证目录写入能力，尚未验证真实知识空间批量下载。`;
    } catch (error) {
      const name = error?.name || 'Error';
      report.result = stage === 'picker' && name === 'AbortError' ? 'picker_aborted' : 'failed';
      report.error = { stage, name, message: String(error?.message || error) };
      status.textContent = report.result === 'picker_aborted'
        ? '目录选择被取消或被浏览器中止，不能据此判定不支持。可重新验证。'
        : `验证失败：${stage}\n${name}: ${report.error.message}\n如果已经创建测试目录，可能留下部分文件，可手动删除。`;
    } finally {
      report.finishedAt = new Date().toISOString();
      render();
      button.disabled = false;
    }
  });
})();
