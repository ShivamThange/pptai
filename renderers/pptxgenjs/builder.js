const fs = require("fs");
const pptxgen = require("pptxgenjs");
const VERSION = require("pptxgenjs/package.json").version;
// Adapted native text/table/chart helpers from hardik-pptxgenjs core/builder.js.
// Source commit and SHA-256 are recorded in PROVENANCE.md. No layout/planner here.
function hexToColor(value) { return String(value || "000000").replace(/^#/, "").toUpperCase(); }
function position(b) { return { x: b.x, y: b.y, w: b.w, h: b.h }; }
function textOptions(obj, theme, size=18) {
  const s = {...theme, ...obj.style};
  return { ...position(obj.box), objectName: obj.object_id,
    fontFace: s.font_name || "Aptos", fontSize: s.font_size || size,
    bold: Boolean(s.bold), italic: Boolean(s.italic), color: hexToColor(s.color || "#0F172A"),
    align: s.align || "left", valign: obj.kind === "heading" ? "mid" : "top",
    // Locked 3.12 text-array order is left, right, bottom, top.
    margin: [7.2, 7.2, 3.6, 3.6], breakLine: false };
}
function renderText(slide, obj, theme) {
  const c = obj.content;
  const text = c.lines ? c.lines.join("\n") : c.text;
  slide.addText(text, textOptions(obj, theme, obj.kind === "heading" ? 32 : 18));
}
function renderList(slide, obj, theme) {
  const items = obj.content.items;
  const options = textOptions(obj, theme, 16);
  const runs = items.map((item,index) => {
    const level = typeof item === "object" ? item.level || 0 : 0;
    return {text: typeof item === "object" ? item.text : String(item),
      options: {breakLine: index<items.length-1,
        bullet: obj.kind === "numbered_list" ? {type:"ul", style:"arabicPeriod", indent:18*(level+1)} : {indent:18*(level+1)},
        hanging:18}};
  });
  slide.addText(runs, options);
}
function renderTable(slide, obj, theme, pageBg) {
  const c = obj.content, s = {...theme, ...obj.style, page_background: pageBg};
  const headers = c.headers || [], rows = c.rows || [];
  const columns = headers.length || (rows[0] || []).length;
  if (!columns || !rows.length || rows.some(r => r.length !== columns)) throw new Error("Invalid table column lengths");
  const table = [];
  if (headers.length) table.push(headers.map(v => ({text:String(v), options:{bold:true,color:"FFFFFF",fill:hexToColor(s.header_bg || "#0F172A")}})));
  for (let i=0;i<rows.length;i++) table.push(rows[i].map(v => ({text:String(v),options:{fill:i%2 ? hexToColor(s.band_bg || "#F8FAFC") : hexToColor(pageBackground(s))}})));
  if (obj.content.merges?.length) {
    const skipped = new Set();
    for (const [r,c,rs,cs] of obj.content.merges) {
      table[r][c].options.rowspan = rs;
      table[r][c].options.colspan = cs;
      for (let i=r;i<r+rs;i++) for (let j=c;j<c+cs;j++) if (i!==r || j!==c) skipped.add(`${i}:${j}`);
    }
    for (let r=0;r<table.length;r++) table[r] = table[r].filter((v,c)=>!skipped.has(`${r}:${c}`));
  }
  slide.addTable(table, {...position(obj.box), objectName:obj.object_id,
    border:{type:"solid",color:"CBD5E1",pt:1}, margin:[2.88,4.32,2.88,4.32],
    valign:"middle", fontFace:s.font_name || "Aptos", fontSize:s.font_size || 13,
    color:hexToColor(s.color || "#334155"), autoPage:false});
}
function pageBackground(s) { return (s && s.page_background) || "FFFFFF"; }
function renderChart(pptx, slide, obj, theme) {
  const c=obj.content, b=obj.box, type=c.chart_type || "column", s={...theme, ...obj.style};
  if (!["bar","column","line","pie","area"].includes(type)) throw new Error("Unsupported chart type");
  if (!c.categories.length || !c.series.length || c.series.some(s => s.values.length !== c.categories.length || s.values.some(v => !Number.isFinite(v)))) throw new Error("Invalid chart lengths/values");
  const data=c.series.map(s => ({name:s.name,labels:c.categories,values:s.values}));
  const opts={...position(b),objectName:obj.object_id,showLegend:c.series.length>1,legendPos:"b",
    catAxisLabelFontFace:s.font_name || theme.font_name || "Aptos",valAxisLabelFontFace:s.font_name || theme.font_name || "Aptos",
    chartColors:(Array.isArray(s.chart_colors) && s.chart_colors.length ? s.chart_colors.map(hexToColor) : undefined),
    showTitle:Boolean(c.title),title:c.title || "",showValue:false,showCatName:false,showSerName:false};
  if (type === "bar" || type === "column") opts.barDir=type === "bar" ? "bar" : "col";
  // Never clamp negative values to zero; let the native axis include the data.
  slide.addChart(pptx.ChartType[type === "column" ? "bar" : type],data,opts);
}
async function renderScene(scene, theme, output) {
  if (scene.schema_version !== "scene-v1" || !scene.slides.length) throw new Error("Unsupported/empty scene contract");
  if (VERSION !== "3.12.0") throw new Error("Install locked PptxGenJS 3.12.0 with npm ci");
  const pptx=new pptxgen();
  pptx.defineLayout({name:"SCENE",width:scene.width_inches,height:scene.height_inches});
  pptx.layout="SCENE"; pptx.author="PPTAI"; pptx.title=scene.title;
  pptx.theme={headFontFace:theme.font_name || "Aptos",bodyFontFace:theme.font_name || "Aptos",lang:"en-US"};
  for (const page of scene.slides) {
    const slide=pptx.addSlide(); slide.background={color:hexToColor(page.background_color)};
    const nodes=new Map(page.objects.map(o => [o.object_id,o]));
    for (const obj of page.objects) {
      switch(obj.kind) {
        case "heading": case "text_group": renderText(slide,obj,theme); break;
        case "bullets": case "numbered_list": renderList(slide,obj,theme); break;
        case "table": renderTable(slide,obj,theme,page.background_color); break;
        case "chart": renderChart(pptx,slide,obj,theme); break;
        case "image": case "formula":
          if (!fs.existsSync(obj.content.path)) throw new Error("Required image asset missing");
          slide.addImage({...position(obj.box),path:obj.content.path,objectName:obj.object_id}); break;
        case "shape": {
          const opts=textOptions(obj,theme,13), s={...theme,...obj.style};
          if (!["rect","roundRect","diamond","ellipse"].includes(obj.content.shape_type || "rect")) throw new Error("Unsupported native shape");
          const shapeType=pptx.ShapeType[obj.content.shape_type || "rect"];
          const fill={color:hexToColor(s.fill || "#EFF6FF")}, line={color:hexToColor(s.line_color || "#3B82F6"),width:s.line_width || 1};
          if (obj.content.text) {
            slide.addText(obj.content.text,{...opts,shape:shapeType,valign:"mid",fill,line}); break;
          }
          // Decorative/background object: no empty addText call (PptxGenJS rejects it).
          slide.addShape(shapeType,{...position(obj.box),objectName:obj.object_id,fill,line}); break;
        }
        case "connector": {
          const from=nodes.get(obj.content.from_id), to=nodes.get(obj.content.to_id);
          if (!from || !to) throw new Error("Unknown connector endpoints");
          const x1=from.box.x+from.box.w, y1=from.box.y+from.box.h/2, x2=to.box.x,y2=to.box.y+to.box.h/2;
          slide.addShape(pptx.ShapeType.line,{x:Math.min(x1,x2),y:Math.min(y1,y2),w:Math.abs(x2-x1),h:Math.abs(y2-y1),
            flipH:x2<x1,flipV:y2<y1,objectName:obj.object_id,line:{color:"64748B",width:1.25}}); break;
        }
        default: throw new Error(`Unsupported required object type: ${obj.kind}`);
      }
    }
    if (page.notes) slide.addNotes(page.notes);
  }
  await pptx.writeFile({fileName:output});
  return {version:VERSION,warnings:[]};
}
if (require.main === module) {
  const [request,output]=process.argv.slice(2);
  if (!request || !output) { console.error("Internal worker usage: builder.js request.json candidate.pptx");process.exit(2); }
  const data=JSON.parse(fs.readFileSync(request,"utf8"));
  renderScene(data.scene,data.theme || {},output).then(result => process.stdout.write(JSON.stringify(result))).catch(error => {console.error(error.stack);process.exitCode=1;});
}
module.exports={renderScene};
