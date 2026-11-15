"""Check stable workspace widths across short and tall tabs; no processing."""
import json


def run(c, wait_for, out):
    evaluate = c.evaluate
    evaluate('''workspaceView.reset();window.geometryFixture={player:document.querySelector('#process-video'),
      frame:document.querySelector('#report-editor'),feed:document.querySelector('#speech-feed'),
      history:history.length};window.geometryMutations=[];window.geometryFetch=fetch;
      window.fetch=(url,options)=>{if(options?.method&&options.method!=='GET')geometryMutations.push(String(url));return geometryFetch(url,options)}''')
    panels = {'transcript': 'stage-speech', 'notes': 'stage-notes', 'article': 'stage-notes',
              'details': 'recording-details', 'processing': 'recording-processing-tab'}
    for width, height in [(1440, 900), (1200, 820), (1024, 768), (760, 560), (375, 820)]:
        c.call('Emulation.setDeviceMetricsOverride', width=width, height=height, deviceScaleFactor=1, mobile=False)
        for layout in ['side', 'stacked']:
            evaluate(f'workspaceView.setLayout({json.dumps(layout)})')
            baseline = None
            for kind in ['transcript', 'details', 'processing', 'notes', 'article', 'transcript']:
                evaluate(f'document.querySelector("#workspace-tab-{kind}").click();scrollTo(0,0)')
                wait_for(lambda: evaluate(f'document.querySelector("#{panels[kind]}").checkVisibility()'))
                evaluate('new Promise(resolve=>requestAnimationFrame(()=>requestAnimationFrame(resolve)))')
                geometry = evaluate('''(()=>{const rect=id=>{const r=document.getElementById(id).getBoundingClientRect();return {x:r.x,y:r.y,width:r.width}};
                  return {pageWidth:document.body.getBoundingClientRect().width,player:rect('shared-player'),
                  tabs:rect('workspace-tabs'),content:rect('workspace-tab-panel'),
                  panel:rect(''' + json.dumps(panels[kind]) + ''')};})()''')
                if baseline is None:
                    baseline = geometry
                else:
                    assert geometry['pageWidth'] == baseline['pageWidth'], (width, layout, kind, baseline, geometry)
                    for node in ['player', 'tabs', 'content']:
                        for axis in ['x', 'y', 'width']:
                            assert abs(geometry[node][axis] - baseline[node][axis]) < 1, (width, layout, kind, node, baseline, geometry)
                assert abs(geometry['panel']['width'] - geometry['tabs']['width']) < 1, (width, layout, kind, geometry)
                assert evaluate('document.documentElement.scrollWidth<=innerWidth+1'), (width, layout, kind)
                if kind in ['details', 'processing']:
                    c.screenshot(out / f'stable-tabs-{kind}-{width}-{layout}.png')
    assert evaluate('geometryMutations') == [], evaluate('geometryMutations')
    assert evaluate('''geometryFixture.player===document.querySelector('#process-video') &&
      geometryFixture.frame===document.querySelector('#report-editor') && geometryFixture.feed===document.querySelector('#speech-feed') &&
      geometryFixture.history===history.length''')
    assert evaluate('window.uiErrors') == [], evaluate('window.uiErrors')
    print('PASS: stable page, player, tab strip and content widths across all five tabs, two layouts and five viewports; DOM/history preserved, no processing', flush=True)
