// Isolated Adobe host substitute; executes the unmodified plugin file transport.
const fs=require('fs'),vm=require('vm'),path=require('path');
const input=JSON.parse(fs.readFileSync(process.argv[2],'utf8')),effects=[];
const folder=dir=>({nativePath:dir,async getEntries(){return fs.readdirSync(dir).map(n=>entry(path.join(dir,n)))},async getEntry(n){const p=path.join(dir,n);if(!fs.existsSync(p))throw Error('missing');return entry(p)},async createFile(n,o){const p=path.join(dir,n);if(!o.overwrite&&fs.existsSync(p))throw Error('exists');return entry(p)}});
const entry=p=>({name:path.basename(p),async read(){return fs.readFileSync(p,'utf8')},async write(data){
 if(input.mode==='receipt-failure'&&p.includes('receipt-')&&JSON.parse(data).status==='native_call_returned')throw Error('SIMULATED_RECEIPT_FAILURE');
 fs.writeFileSync(p,data);}});
const seq={name:'Current sequence',guid:'sequence-1',getFrameSize:async()=>({width:720,height:1280}),getInPoint:async()=>({seconds:0,ticks:'0'}),getOutPoint:async()=>({seconds:1,ticks:'254016000000'}),getEndTime:async()=>({seconds:1,ticks:'254016000000'}),getTimebase:async()=>10584000000,getAudioTrackCount:async()=>0,getCaptionTrackCount:async()=>0};
if(input.mode==='wrong-guid')seq.guid='sequence-2';
const project={path:input.project_path,guid:'project-1',getActiveSequence:async()=>seq,getSequences:async()=>[seq],
 save:async()=>{throw Error('IN_PLACE_SAVE_FORBIDDEN')},
 saveAs:async p=>{effects.push('saveAs');fs.writeFileSync(p,'current-unsaved-memory',{flag:'wx'});project.path=p;
  if(input.mode==='change-during-save')fs.writeFileSync(input.copy_path,'external-user-edit');
  if(input.mode==='save-failure')throw Error('SIMULATED_SAVE_OUTCOME_UNKNOWN');return true;}};
const ppro={Project:{getActiveProject:async()=>project,open:async p=>{effects.push('open');project.path=p;return project;}},
 OpenProjectOptions:class{setShowConvertProjectDialog(){return this}setShowLocateFileDialog(){return this}setShowWarningDialog(){return this}},
 Constants:{ExportType:{IMMEDIATELY:0}},EncoderManager:{getManager:()=>({exportSequence:async(s,t,out)=>{effects.push('export');if(input.mode==='unknown')throw Error('SIMULATED_CHANNEL_LOSS_AFTER_ACCEPTANCE');if(input.media)fs.copyFileSync(input.media,out);return input.mode!=='false-return';}})}};
const uxp={host:{name:'fake-premiere',version:'test'},storage:{localFileSystem:{getDataFolder:async()=>folder(input.receipts),getPluginFolder:async()=>folder(input.mailbox)}},entrypoints:{setup(){}}};
const context=vm.createContext({require:n=>n==='premierepro'?ppro:uxp,document:{getElementById:()=>null},setTimeout,setInterval:()=>0,clearInterval(){}});
vm.runInContext(fs.readFileSync(input.plugin,'utf8'),context);
(async()=>{await vm.runInContext(input.mode==='heartbeat'?'enabled=true;heartbeat()':input.mode==='stopped'?'enabled=true;stop()':'enabled=true;poll()',context);console.log(JSON.stringify({effects,project_path:project.path,real_adobe:false}));})().catch(e=>{console.error(e);process.exitCode=1});
