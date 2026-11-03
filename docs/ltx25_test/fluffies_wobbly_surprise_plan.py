"""Fresh Fluffies comedy: selected vault opener, eight cast members, varied cuts."""
import json
import math
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
OUT = ROOT/'state/fluffies_ep02_carnival'
CAST = {
 'Bobo':'blue rounded bean-shaped Fluffie, sapphire/sky-blue fur and icy-blue cheeks/belly, teal eyes, one swept crown tuft; match the user-selected opener',
 'Lulu':'pink petite round Fluffie, rose/magenta fur with blush face/belly, teal eyes and split soft crown tuft; match the user-selected opener',
 'Zuzu':'tall soft pear-shaped purple Fluffie, violet/lavender fur, hazel eyes, three short crown tufts',
 'Numi':'pearl-white upright oval Fluffie, ivory highlights and silver shadows, ice-blue eyes, one forward fluffy crown tuft',
 'Pebble':'squat rounded-square charcoal/soft-black Fluffie, graphite sides and silver-grey face/belly, amber eyes, broad swept crest',
 'Pip':'small coral-red pear-shaped Fluffie, brown eyes, single curled crown tuft',
 'Momo':'broad lemon-yellow cushion-shaped Fluffie, gentle brown eyes, swept crown tuft',
 'Tiki':'slender mint-green jellybean Fluffie, green eyes and two side tufts',
}
STYLE = ('Original premium 3D animated family comedy, tactile groomed fur with soft secondary motion, '
 'appealing expressive eyes, tiny mitten paws and broad soft feet, springy grounded body weight. '
 'A coherent storybook village with crafted materials, cinematic soft sunlight, warm/cool colour separation, '
 'deep layered sets, foreground framing, realistic contact shadows, clear silhouettes and clean lens composition. ')
SETS = {
 'lane':'Pastel storybook village lane: warm apricot plaster bakery at left, turquoise shutters, arched oak door, rose-pink shop awning, rounded grey cobbles, flower boxes, distant lavender hills. No readable signs.',
 'bakery':'Cozy professional animated-film bakery interior: honey-coloured oak counter, mint cabinets, arched window with golden morning beams, pink tiled wall, copper bowls, flour-dusted wood floor. Keep background props restrained.',
 'workshop':'Open-sided village craft workshop under a teal canvas shade: pale timber workbench, ribbon spools, a low round pink stool, sunlit leaves behind. Cream/teal palette with coral accents.',
 'bridge':'Short broad wooden footbridge over a shallow turquoise creek beneath lilac wisteria, rounded moss stones and layered willow foliage. Pale warm timber deck, low curved rails, village terrace visible at the far end.',
 'terrace':'Festive garden terrace above the village: pale stone paving, a broad spreading flowering tree, pink-and-cream striped canopy, low oval oak party table, colourful triangular bunting with NO text, soft blue/pink/purple balloons, cream balustrade and distant lavender hills. Golden afternoon backlight.',
 'arch':'Flower-covered stone arch at the entrance to the party terrace, warm apricot wall at left, leafy hedge at right, glimpses of pink/cream canopy beyond, sunlit cream paving. Connect spatially to the terrace.',
}
CAKE = ('The single cake is a broad ONE-tier round vanilla cake with white whipped icing, one rose-pink side stripe, '
 'a few pink icing rosettes and a single short mint candle. It rests on one round silver cake board. '
 'Transport uses one LOW red wooden handcart with four small cream wheels and a short red handle. ')
# title, seconds, cast, set, exact opening instant, visible action, camera, sound
ROWS = [
 ('A very suspicious stroll',6.5,['Bobo','Lulu'],'lane',
  'Lulu at screen right is mid-backward skip, holding Bobo\'s paw and tugging gently. Bobo at left is mid-forward step, curious, looking at Lulu rather than the camera. Both full bodies and travelling room at right.',
  'Lulu skips backwards down the lane pulling Bobo along for four clear alternating steps. Bobo tries to glance behind; Lulu pivots into Bobo\'s view with an exaggerated innocent grin while both keep travelling.',
  'Low 35mm lateral tracking; foreground flowers sweep past and cobbled landmarks visibly pass behind them.',
  'Two different quick footstep rhythms, Lulu\'s conspiratorial breathy giggle, Bobo\'s short curious rising chirp.'),
 ('An ambitious cake',6,['Momo','Pebble'],'bakery',
  'Momo at left and Pebble at right already support opposite edges of the silver cake board over the low red cart. Knees bent, cake hovering just above the cart bed, faces focused on the shared weight. Candle unlit.',
  'They take two coordinated shuffling steps and lower the cake onto the cart. Momo lets go proudly; the soft icing wobbles and Pebble quickly steadies the board with both paws. One shared heavy-object gag.',
  'Medium-wide three-quarter dolly in, keeping paws, board, cart and feet in one clear frame.',
  'Warm rounded effort puffs, two wooden foot shuffles, soft cart creak, Pebble\'s short surprised grunt and relieved chuckle.'),
 ('Pip becomes the bow',4,['Pip','Tiki'],'workshop',
  'Pip and Tiki stand on opposite sides of the bench, each gripping one end of a loose broad pink ribbon. Pip is already leaning back and Tiki is already stepping sideways; the ribbon makes a single loose loop in front of Pip.',
  'They pull in opposite directions; the loose loop flops around Pip\'s fluffy middle like an enormous bow. Pip turns once in surprise while Tiki steps closer and catches the loose end. Gentle fabric, no tight restraint.',
  'Close full-body 40mm framing, slight sideways slide following Pip\'s turn, clear ribbon geometry.',
  'Soft ribbon swish and springy flutter, Pip\'s startled squeak, Tiki\'s airy amused chuckle.'),
 ('Decorating with style',5,['Zuzu','Numi'],'terrace',
  'Zuzu stands on a LOW two-step platform reaching toward a loose bunting string, one foot already shifting for balance. Numi below walks past holding three balloon strings and looks upward. Keep the platform visibly low and stable.',
  'Zuzu stretches to hook the bunting, the ribbon brushes the nose and triggers one little sneeze. Numi reacts with a tiny hop; the three balloons bob overhead and gently bump Zuzu\'s crown tuft. Both recover with amused grins.',
  'Slightly low medium-wide diagonal composition using canopy lines, gentle rising camera matching the reaching gesture.',
  'Wooden step tap, a short nonverbal sneeze, soft balloon squeaks, Numi\'s tiny gasp and Zuzu\'s sheepish chuckle.'),
 ('No peeking',5,['Bobo','Lulu'],'lane',
  'Both already walking screen right around a curved cobbled corner. Lulu beside Bobo holds one paw in front of Bobo\'s sightline; Bobo leans sideways mid-step trying to peek past it. No blindfold.',
  'Bobo leans left then right to peek around Lulu\'s paw while they walk. Lulu matches each sidestep without stopping and gently turns Bobo toward the next corner, laughing quietly.',
  'Medium two-shot tracking backwards ahead of their visible steps, 50mm character focus and layered village bokeh.',
  'Quick soft footsteps, two questioning Bobo chirps, Lulu\'s suppressed nonverbal giggles.'),
 ('Out of the bakery',6,['Momo','Pebble'],'lane',
  'At the bakery archway, Momo is mid-push behind the red cart; Pebble walks beside it with one paw near the cake board. The cake is secure on the cart, mint candle unlit. Doorway creates a dark frame around bright sunlit fur.',
  'Momo pushes the cake cart through the doorway and into the lane. The front wheels roll over the shallow threshold, the cake gives a small wobble, and Pebble walks sideways in a funny protective shuffle to steady it as they keep moving.',
  'Low wheel-height three-quarter tracking into sunlight; roll past the threshold and reveal the lane with real parallax.',
  'Rolling little wheels, a wooden threshold clack, Momo\'s steady effort puffs, Pebble\'s two worried little hums.'),
 ('The bridge wobble',6,['Momo','Pebble'],'bridge',
  'The red cake cart is already rolling onto the bridge from left to right. Momo pushes at left; Pebble ahead at right walks backwards watching the cake, arms open ready to steady it. Candle still unlit.',
  'A front wheel crosses one raised wooden board. The cake rocks once; Pebble sidesteps quickly and supports the silver board while Momo slows the cart with two short planted steps. They exchange a relieved look while continuing forward.',
  'Wide low side tracking across the creek with willow leaves in the near foreground; full cart and feet visible.',
  'Wooden wheel rattle, a gentle board clonk, short paired gasps, creek ambience and relieved breathy chuckles.'),
 ('Ribbon delivery',5,['Pip','Tiki'],'bridge',
  'Pip and Tiki are jogging right beside the bridge approach carrying the broad pink ribbon between them. One loose trailing ribbon end lies over a rounded low post; their next steps have already begun.',
  'The loose end catches gently on the low post. Pip takes one extra bouncy step and swivels back; Tiki stops with a soft wobble and points at the loop. They hurry back together rather than pulling hard.',
  'Wide 35mm pan following the jog, then a short pan back with their turn; the post and ribbon stay readable.',
  'Light running taps, cloth flutter, a soft elastic twang, Pip\'s surprised squeak and Tiki\'s questioning chirp.'),
 ('Lulu improvises',4,['Bobo','Lulu'],'lane',
  'At a flower shop window on the same lane, Bobo is mid-step turning toward a reflection; Lulu is already hopping into the space between Bobo and the glass with both paws raised in a silly gesture.',
  'Lulu does an exaggerated two-step sidestep and silly shoulder shimmy to capture Bobo\'s attention. Bobo laughs and imitates one step; they continue along the lane together.',
  'Medium full-body two-shot at a different diagonal angle; brief push toward the shared imitation, keep feet.',
  'Two playful shoe-less foot taps, Lulu\'s breathy comic trill, Bobo\'s short delighted giggle.'),
 ('A balloon ballet',5,['Zuzu','Numi'],'terrace',
  'Zuzu has stepped down and is mid-tip-toe flourish beneath the canopy; Numi follows behind holding three balloon strings, one foot raised to imitate the step. Both full bodies against open pale paving.',
  'Zuzu performs a sweeping tip-toe step and half-turn; Numi imitates and the balloons lag then bob over Zuzu\'s head. Zuzu ducks under them with an exaggerated bow and Numi giggles while stepping around.',
  'Graceful lateral arc of less than a quarter turn, 40mm, canopy shadows moving across foreground paving.',
  'Tiny toe taps, soft balloon rubs, an airy whoosh on the bow and Numi\'s delicate delighted giggle.'),
 ('Pebble gets the icing',6,['Momo','Pebble'],'bridge',
  'Cart near the far end of the bridge. Momo leans into the handle mid-push; Pebble walks beside the slightly leaning cake board, looking upward at a loose white icing dollop at the cake edge. No icing on Pebble yet.',
  'A small cart jolt makes one soft white icing dollop plop onto Pebble\'s dark nose. Pebble freezes for only a brief comic blink, crosses the eyes toward the icing and sneezes a tiny puff. Momo keeps rolling slowly and chuckles warmly.',
  'Medium two-shot tracking, then gentle focus shift from wobbling icing to Pebble\'s nose, cart stays visible.',
  'Small wheel clack, wet soft plop, Pebble\'s short comic sneeze, Momo\'s rounded chuckle.'),
 ('A three-legged ribbon dance',5,['Pip','Tiki'],'bridge',
  'Pip and Tiki have freed the post but a very loose ribbon loop drapes around both waists, with plenty of slack and no knots. They are mid-step together, looking down at the shared loop with amused confusion.',
  'They try two mismatched steps, wobble, then synchronize into three bouncy side-by-side hops. The loose ribbon slips down harmlessly and they catch its ends while laughing, finally moving together.',
  'Clear full-body frontal travelling shot moving backwards ahead of them, low camera, broad readable silhouettes.',
  'Alternating grass/wood taps becoming paired soft thumps, ribbon swishes and two distinct nonverbal giggles.'),
 ('Numi hides the evidence',4,['Zuzu','Numi'],'arch',
  'Numi is already stepping behind the flowering arch with the balloon bouquet while Zuzu waves from beside the wall. Numi\'s pearl-white head and balloon strings remain visible; balloon tops peek over the arch.',
  'Numi ducks behind the arch to hide the balloons, but they float back into view. Zuzu gently tugs the strings lower, making Numi pop up on tiptoe in surprised imitation; they both duck down giggling.',
  'Low medium-wide framed through foreground flowers; one restrained pan up with the balloons and down with the reaction.',
  'Light quick foot taps, rubbery balloon squeaks, Numi\'s tiny rising squeak and Zuzu\'s soft conspiratorial chuckle.'),
 ('The not-quite-perfect cake',6,['Momo','Pebble','Zuzu'],'terrace',
  'Momo and Pebble already lift the silver board from the red cart beside the low party table. Zuzu steps toward them with arms extended. Cake slightly lopsided; Pebble has a small white icing dab on the dark nose. Candle unlit.',
  'They lower the slightly crooked cake onto the table. Zuzu turns the board a little to find a flattering angle; the cake still leans the other way. All three tilt their heads together, then shrug and smile with affectionate acceptance.',
  'Medium-wide 50mm dolly in with the lowering motion, clear three-way eyelines and table edge in foreground.',
  'Three soft effort breaths, silver board tap, icing squish, a questioning purple hum and warm sheepish chuckles.'),
 ('The final distraction',5,['Bobo','Lulu'],'arch',
  'Lulu and Bobo are already walking into the flower-covered arch. Lulu has one foot turning toward the terrace and a paw behind the back signalling offscreen; Bobo leans forward with curiosity mid-stride.',
  'Lulu takes two playful sideways steps, then gently turns Bobo around the arch. Bobo catches a glimpse of the decorations and speeds into a delighted little trot as Lulu follows.',
  '35mm follow from behind three-quarter, passing the arch pillar as a natural foreground wipe into warm party light.',
  'Footsteps speeding up, leaf rustle, Lulu\'s excited breathy giggle, Bobo\'s surprised happy gasp.'),
 ('Last-minute helpers',5,['Pip','Tiki','Numi'],'terrace',
  'Pip and Tiki are jogging toward two low canopy posts with the freed pink ribbon stretched loosely between them. Numi already reaches for one end while holding balloon strings in the other paw.',
  'Pip and Tiki jog into place and Numi catches the ribbon end. They lift it together into one generous decorative loop between the posts; Pip ducks underneath with a proud little hop and all three smile at the finished decoration.',
  'Wide diagonal tracking alongside the running pair, opening the frame to show Numi and the decorated terrace.',
  'Quick footfalls, a ribbon swish and three light pleased nonverbal chirps; balloons bob softly.'),
 ('Surprise!',7,list(CAST),'terrace',
  'Wide party reveal: Bobo and Lulu enter from front left mid-stride; Momo and Pebble stand beside the table; Zuzu and Numi emerge beside the canopy; Pip and Tiki step out from the ribbon posts. Exactly eight distinct Fluffies. Cake on table, one mint candle now has a tiny warm flame; Pebble\'s nose has white icing.',
  'The friends spring out with open paws and happy little bounces as Bobo and Lulu enter. Bobo takes two delighted quick steps toward the table, turns to see the colourful friends on both sides and laughs. Everyone remains separate and clearly visible, with small individual waves rather than crossing paths.',
  'Wide 28mm gentle crane up and short pull-back to reveal the entire authored party set, then settle as Bobo reaches the cake.',
  'An affectionate burst of varied nonverbal happy squeaks and giggles, soft landing thumps, bunting flutter and balloons. Nobody says a word.'),
 ('Bobo makes it better',6,['Bobo','Lulu','Pebble'],'terrace',
  'Medium at the cake table: Bobo leans forward in an already-begun step, Lulu at one side and charcoal Pebble at the other. Pebble has white icing on the nose and looks sheepish; Bobo\'s nose is still clean. Crooked cake in foreground.',
  'Bobo notices Pebble\'s icing nose, touches one small dab of icing from the cake edge and puts it on Bobo\'s own blue nose with a proud grin. Pebble\'s worried face opens into laughter; Lulu gives Bobo an affectionate shoulder nudge. A clear caring visual punchline.',
  '50mm intimate three-shot, small push with Bobo\'s gesture, keep both contrasting icing noses in the same focus plane.',
  'One tiny icing squish, Bobo\'s bright giggle, Pebble\'s relieved rounded laugh and Lulu\'s warm breathy chuckle.'),
 ('White fur needs pink icing',6,['Zuzu','Numi'],'terrace',
  'Zuzu and Numi stand side by side at the far end of the party table. Zuzu already holds one tiny pink icing dab on a mitten fingertip; Numi leans forward mid-bob, curious and cheerful. Numi\'s nose still clean.',
  'Zuzu gently dabs pink icing onto Numi\'s white nose. Numi goes cross-eyed to inspect it, then bounces with delighted giggles and returns a tiny dab to Zuzu\'s purple cheek. They lean shoulder-to-shoulder laughing. Keep it light and affectionate.',
  'Playful eye-level close two-shot with shallow but readable background bokeh; slight lateral move follows the reciprocal dab.',
  'Two tiny soft icing plips, Numi\'s rising amused chirp, Zuzu\'s surprised little gasp and shared giggles.'),
 ('A wonderfully wobbly party',7.5,list(CAST),'terrace',
  'All eight around the low party table, Bobo nearest the single lit mint candle and Lulu beside Bobo. Bobo and Pebble have little white icing noses; Numi a pink icing nose; Zuzu a pink cheek dab. The same slightly crooked one-tier cake and canopy/ribbons remain. Everyone already mid-small step or bounce, not posing for a photo.',
  'Bobo leans in and blows the little candle out with one soft puff. The friends do a happy bouncy two-step around the table, giggling at their icing noses. Pip ducks under the pink ribbon and pops back beside Tiki, while Lulu takes Bobo\'s paw. The camera rises and pulls back to the whole glowing terrace, ending on shared lively celebration rather than a rigid pose.',
  'Wide 28mm gradual crane and pull-back over the balustrade, clear table and all eight colour silhouettes, finish with gentle continuing motion.',
  'One short candle puff, a tiny flame-out tick, light dance steps, eight warm nonverbal giggles, soft leaves and bunting flutter. No spoken words or song.'),
]


def build():
    for folder in ['frames','clips','prompts']:
        (OUT/folder).mkdir(parents=True, exist_ok=True)
    shots=[]
    at=10.0
    for number,row in enumerate(ROWS,1):
        title,length,cast,location,opening,action,camera,sound=row
        requested=math.ceil(length+2.5)
        identities='; '.join(CAST[c] for c in cast)
        prop=CAKE if number in [2,6,7,11,14,17,18,20] else ''
        continuity=('Cake mint candle unlit.' if number<17 else 'Single mint candle lit until the final puff; icing marks only where specified.') if prop else ''
        image_prompt=(STYLE+SETS[location]+' '+prop+continuity+' '
          'Make ONE finished cinematic landscape opening frame, a film still caught DURING movement rather than a lineup or posed portrait. '
          'Visible cast ONLY: '+identities+'. Exact opening instant: '+opening+' '
          'Use varied camera placement, foreground/background depth, off-camera eyelines, planted weight and separated readable limbs. '
          'No lettering, subtitles, logo, watermark, collages, extra cast or duplicate characters. Keep faces natural and appealing. '+camera)
        video_prompt=(STYLE+SETS[location]+' '+prop+continuity+' '
          'Preserve the exact opening-frame characters: '+identities+'. '
          f'This is a {requested}-second single shot with movement already underway in the opening frame. '
          'Continue that movement IMMEDIATELY and sustain visible changing body positions through the shot. No initial freeze or posed establishing hold. '
          'Action: '+action+' Camera: '+camera+' '
          'Use actual steps, weight transfer, responsive paws and grounded contacts. No slow motion or stationary mouth-acting. '
          'SOUND: '+sound+' Short character vocal reactions must suit the visible action. '
          'No speech, words, language, gibberish conversation, narration, lyrics or singing. No generated background music; original instrumental music is added in the edit. '
          'No internal cuts, new characters, disappearing cast, colour swaps or changing props. Keep the physical gag simple and readable.')
        shot=dict(id=f'C{number:02d}',number=number,title=title,cast=cast,location=location,
          duration=requested,edit_seconds=length,edit_frames=round(length*24),trim_start_frame=60,
          start=at,end=at+length,seed=1025000+number,frame=f'frames/C{number:02d}.png',
          clip=f'clips/C{number:02d}.mp4',image_prompt=image_prompt,video_prompt=video_prompt,
          opening=opening,action=action,camera=camera,sound=sound,audio_intent='non_lipsync',transition='hard cut')
        assert requested<=10 and 60+shot['edit_frames']<=requested*24
        shots.append(shot)
        for kind in ['image','video']:
            (OUT/'prompts'/f'{shot["id"]}-{kind}.txt').write_text(shot[f'{kind}_prompt'],encoding='utf-8')
        at+=length
    assert at==120 and sum(s['edit_frames'] for s in shots)==2640
    spec=dict(schema='execution_manifest.v1',title='Fluffies — The Wobbly Surprise',fps=24,
      total_seconds=110,total_frames=2640,full_episode_seconds=120,full_episode_frames=2880,
      intro_seconds=10,intro_frames=240,intro='state/fluffies_ep02_carnival/refs/1002475080.mp4',
      intro_vault_id='abaee350db914237bbd563fd49afde89',intro_sha256='3cf3973f41294e8a301b442817a3dff72b438c21f8b21d6cf675651d9583e7b5',
      output_width=1920,output_height=1080,
      score_file='wobbly_original_score_120s.wav',
      settings=dict(engine='ltx',mode='opening',steps='8',ltx_quality='balanced',aspect_ratio='16:9',ltx_sharp_decode='true',ltx_calm_sampler='false',no_audio='false'),
      shots=shots,master_filename='Fluffies_The_Wobbly_Surprise_120s.mp4',
      audio_policy='Keep selected opener in full with its existing sound; preserve native story reactions/effects with identical source trims; mix original instrumental music under story only.',
      review='User visual/listening review; no AGY, subagents or strict inspection gates')
    (OUT/'manifest.json').write_text(json.dumps(spec,indent=2),encoding='utf-8')
    def tc(t):
        return f'{int(t)//60:02d}:{int(t)%60:02d}'+('.5' if t%1 else '')
    lines=['# Fluffies — The Wobbly Surprise','',
      '## User direction and chosen opener','',
      'Fresh funny episode with more characters, professional scene design and real movement. The old Shortcut generations are stopped and must not resume. '
      'Use the user-selected **1002475080.mp4** in full: vault `abaee350db914237bbd563fd49afde89`, ten seconds, 1920×1080, 24 fps, original audio. '
      'Its downloaded SHA-256 matches the vault; ffprobe and full FFmpeg decode passed. No new intro generation.','',
      '## Story','',
      'Lulu distracts Bobo while the other six friends prepare a surprise party. Momo and Pebble deliver a wobbling cake; Pip and Tiki struggle with a ribbon; '
      'Zuzu and Numi decorate the terrace. Their plans become messy, but Bobo makes an icing nose to match embarrassed Pebble and turns the mistakes into the fun. '
      'The ending celebrates the friends rather than a perfect cake. The new blue/pink pair leads; all eight characters have purposeful action and comic reactions.','',
      '## Visual treatment','',
      'Four distinct spaces plus their connecting arch: golden bakery interior, pastel cobbled village lane, cool lilac/turquoise creek bridge, and warm sunlit party terrace. '
      'Use authored foreground framing, layered sets, warm/cool separation, readable paw contacts and eye-level character staging. '
      'Vary 28–50 mm views and camera height. Tracking follows travel; pushes reveal a reaction; wide cranes reveal the party. No arbitrary orbit or repeated front-facing portrait setup.','',
      'Most shots use two or three characters. All eight appear in two planned wide reveals, limiting crowd complexity. '
      'Blue Bobo and pink Lulu follow the selected opener; Lulu\'s eyes are teal here. Other cast: purple Zuzu, white Numi, charcoal/silver Pebble, coral Pip, yellow Momo, mint Tiki. '
      'All share groomed fur, tiny paws and soft feet. No clothes, speech or narration.','',
      '## Cut structure','',
      'The selected opener lasts ten seconds; twenty story cuts total 110 seconds. Cut lengths vary from four to 7.5 seconds for setup, escalation, reaction and payoff. '
      'Every source has a removable 2.5-second lead-in. Default source start is frame 60; picture and native sound receive the same trim. '
      'Openings are actual mid-action film frames, not a cast pose. All picture transitions are hard cuts. Full master: 2880 frames / two minutes at 24 fps, 1920×1080.','',
      '| Shot | Timeline | Cast | Location / action | Camera |','| --- | --- | --- | --- | --- |',
      '| Opener | 00:00–00:10 | Selected blue/pink intro | User-selected 1002475080.mp4, complete original sound | Preserve full clip |']
    for s in shots:
        lines.append(f'| {s["id"]} · {s["title"]} | {tc(s["start"])}–{tc(s["end"])} | {", ".join(s["cast"])} | {s["location"]}: {s["action"]} | {s["camera"]} |')
    lines+=['','## Assets, audio and execution','',
      '- Plan source: `docs/ltx25_test/fluffies_wobbly_surprise_plan.py`; frozen prompts/manifest and art: `state/fluffies_ep02_carnival/`.',
      '- Build stills directly with built-in ImageGen, using character references and actual location/prop reference frames. Do not use the app Image Lab.',
      '- Video uses the main app on 8787 and one ComfyUI on 8190: existing LTX Balanced landscape, eight steps, sharp decode on, calm sampler off, native audio on. No runtime/model/workflow changes.',
      '- Render: `python docs/ltx25_test/tumble_puffs_ep01/episode_runner.py render --out state/fluffies_ep02_carnival`.',
      '- Score: run `docs/ltx25_test/fluffies_wobbly_score.py` with the bundled media Python (numpy). Its first ten seconds are silent so the selected opener keeps its soundtrack.',
      '- Finish/publish: `python docs/ltx25_test/fluffies_shortcut_finish.py --out state/fluffies_ep02_carnival --wait --publish`.',
      '- Prefix preview: the same editor supports `--preview N`; it uses the complete chosen opener and the first N completed story shots, with the same motion trims and audio policy.',
      '- Journal before POST; no blind retries. A STOPPED.json marker prevents new submissions without canceling a current render. Honor user stops.',
      '- Create an original light orchestral/pizzicato/woodwind score at 120 BPM, with playful preparation, bridge tension, warm reveal and celebration. Leave opener audio intact; no score over its first ten seconds.',
      '- Keep generated footfalls, effort sounds, gasps, sneezes and giggles. Duck music under native sound; never replace all audio with music. No spoken words or singing.',
      '- Assemble exact trims, normalize story sources into the selected opener\'s 1080p canvas, verify all source/master streams with ffprobe and full FFmpeg decode, then publish in the Video Vault.',
      '- User is the visual/listening reviewer. No AGY or subagents. Apply the storyboard-editor and visual-director skills directly without delegated review or strict inspection gates.',
      '- Preserve old episode assets and stopped producers. The selected opener is authoritative; the generated eight-character v4 intro is superseded for this episode.','']
    Path(__file__).with_name('FLUFFIES_WOBBLY_SURPRISE_PLAN.md').write_text('\n'.join(lines),encoding='utf-8')
    print(json.dumps(dict(shots=len(shots),story_seconds=110,opener_seconds=10,full_seconds=120,manifest=str(OUT/'manifest.json'))))


if __name__=='__main__':
    build()
