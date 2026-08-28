# Check PR_bndry (GDS layer 0/0) on AI_BYTE submission GDSes.
paths = [
  "/home/aymen/Documents/AI_BYTE_accelerator/chipathon-2026-AI_Byte/gds/ai_byte_top.gds",
  "/home/aymen/Documents/AI_BYTE_accelerator/chipathon-2026-AI_Byte/final_core/gds/ai_byte_top.gds",
  "/home/aymen/Documents/AI_BYTE_accelerator/chipathon-2026-AI_Byte/run_period_140ns/RUN_2026-08-13_02-52-38/final/gds/ai_byte_top.gds",
]

paths.each do |path|
  unless File.exist?(path)
    puts "MISSING: #{path}"
    next
  end

  ly = RBA::Layout::new
  ly.read(path)
  top = ly.top_cell
  li = ly.layer(0, 0)
  dbu = ly.dbu

  flat_shapes = 0
  flat_area = 0.0
  flat_bbox = nil
  if top
    iter = RBA::RecursiveShapeIterator::new(ly, top, li)
    while !iter.at_end?
      flat_shapes += 1
      sh = iter.shape
      if sh.is_box?
        b = iter.trans * sh.box
        flat_area += b.area
        flat_bbox = flat_bbox.nil? ? b : (flat_bbox + b)
      elsif sh.is_polygon?
        p = sh.polygon.transformed(iter.trans)
        flat_area += p.area
        flat_bbox = flat_bbox.nil? ? p.bbox : (flat_bbox + p.bbox)
      elsif sh.is_path?
        p = sh.path.polygon.transformed(iter.trans)
        flat_area += p.area
        flat_bbox = flat_bbox.nil? ? p.bbox : (flat_bbox + p.bbox)
      end
      iter.next
    end
  end

  top_direct = 0
  if top
    top.shapes(li).each { top_direct += 1 }
  end

  puts "=" * 72
  puts path
  puts "  top_cell=#{top ? top.name : 'NONE'}  dbu=#{dbu}"
  puts "  top-cell direct 0/0 shapes=#{top_direct}"
  puts "  flattened-from-top 0/0 shapes=#{flat_shapes} area_um2=#{flat_area * dbu * dbu}"
  if flat_bbox
    puts "  bbox_um=(#{flat_bbox.left * dbu},#{flat_bbox.bottom * dbu})-(#{flat_bbox.right * dbu},#{flat_bbox.top * dbu})"
    w = (flat_bbox.right - flat_bbox.left) * dbu
    h = (flat_bbox.top - flat_bbox.bottom) * dbu
    puts "  size_um=#{w} x #{h}"
    puts "  RESULT: PR_bndry / 0/0 PRESENT"
  else
    puts "  RESULT: PR_bndry / 0/0 MISSING"
  end
end
