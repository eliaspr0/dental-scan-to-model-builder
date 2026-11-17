import os, struct, sys, tempfile, unittest
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from dentalbase_gui import stl_io, jobs


def write_binary(path, n=2):
    with open(path, 'wb') as f:
        f.write(b'\0' * 80 + struct.pack('<I', n) + b'\0' * (50 * n))


class T(unittest.TestCase):
    def test_binary_check(self):
        d = tempfile.mkdtemp()
        b = os.path.join(d, 'a.stl'); write_binary(b)
        self.assertTrue(stl_io.check_binary_stl(b)[0])
        a = os.path.join(d, 'ascii.stl'); open(a, 'w').write('solid x\nfacet normal 0 0 1\nendsolid x\n')
        ok, msg = stl_io.check_binary_stl(a); self.assertFalse(ok); self.assertIn('ASCII', msg)
        t = os.path.join(d, 'trunc.stl'); open(t, 'wb').write(open(b, 'rb').read()[:-10])
        self.assertFalse(stl_io.check_binary_stl(t)[0])
        z = os.path.join(d, 'zero.stl'); write_binary(z, 0); self.assertFalse(stl_io.check_binary_stl(z)[0])
        self.assertFalse(stl_io.check_binary_stl(os.path.join(d, 'missing.stl'))[0])
        # binary STL whose header starts with 'solid' is still accepted (common exporter quirk)
        s = os.path.join(d, 'solidhdr.stl'); open(s, 'wb').write(b'solid exporter'.ljust(80, b' ') + struct.pack('<I', 1) + b'\0' * 50)
        self.assertTrue(stl_io.check_binary_stl(s)[0])

    def test_output_path(self):
        self.assertEqual(stl_io.output_path('/x/y/scan.stl'), '/x/y/scan_output.stl')
        self.assertEqual(stl_io.output_path('/x/y/Scan.STL'), '/x/y/Scan_output.stl')
        self.assertEqual(stl_io.output_path('/x/a.b.stl'), '/x/a.b_output.stl')

    def test_roles(self):
        self.assertEqual(stl_io.guess_role('/a/upper_new.stl'), 'upper')
        self.assertEqual(stl_io.guess_role('/a/Lower2.stl'), 'lower')
        self.assertEqual(stl_io.guess_role('/a/patient.stl'), 'single')

    def test_plan(self):
        f = [('/a/u.stl', 'upper'), ('/a/l.stl', 'lower'), ('/a/x.stl', 'single')]
        j = jobs.plan_jobs(f, True)
        self.assertEqual([x.kind for x in j], ['pair', 'single'])
        self.assertEqual(j[0].outputs, ['/a/u_output.stl', '/a/l_output.stl'])
        self.assertEqual([x.kind for x in jobs.plan_jobs(f, False)], ['single'] * 3)
        self.assertEqual([x.kind for x in jobs.plan_jobs(f[:1], True)], ['single'])   # need both arches for a pair

    def test_args(self):
        o = jobs.Options(offset=3.5)
        a = jobs.build_args(jobs.Job('single', ['/a/u.stl'], ['/a/u_output.stl']), o, 'make_base.py', python='py')
        self.assertEqual(a[:5], ['py', '-u', 'make_base.py', '/a/u.stl', '/a/u_output.stl'])
        self.assertIn('3.5', a)
        p = jobs.build_args(jobs.Job('pair', ['/u', '/l'], ['/uo', '/lo']), o, 'make_base.py', python='py')
        self.assertIn('--pair-out', p)

    def test_strip_option(self):
        j = jobs.Job('single', ['/a/u.stl'], ['/a/u_output.stl'])
        self.assertNotIn('--strip', jobs.build_args(j, jobs.Options(), 'make_base.py', python='py'))
        a = jobs.build_args(j, jobs.Options(strip=1.5), 'make_base.py', python='py')
        self.assertEqual(a[a.index('--strip') + 1], '1.5')

    def test_follow_tips_option(self):
        j = jobs.Job('single', ['/a/u.stl'], ['/a/u_output.stl'])
        self.assertNotIn('--follow-tips', jobs.build_args(j, jobs.Options(), 'make_base.py', python='py'))
        self.assertIn('--follow-tips', jobs.build_args(j, jobs.Options(follow_tips=True), 'make_base.py', python='py'))
        p = jobs.Job('pair', ['/u', '/l'], ['/uo', '/lo'])
        self.assertIn('--follow-tips', jobs.build_args(p, jobs.Options(follow_tips=True), 'make_base.py', python='py'))

    def test_report(self):
        self.assertIsNone(jobs.parse_report('[ 1.0s] loaded'))
        r = jobs.parse_report('{"watertight": true, "euler": 2, "crown_exact_pct": 100.0}')
        self.assertTrue(r['watertight'])
        self.assertIn('teeth exact 100', jobs.summarize(r))
        self.assertIn('tunnels', jobs.summarize({'watertight': True, 'euler': -2}))

    def test_stage(self):
        self.assertEqual(jobs.parse_stage('@@STAGE 3/7 Finding the teeth'), (3, 7, 'Finding the teeth'))
        self.assertIsNone(jobs.parse_stage('[ 1.0s] loaded'))
        self.assertIsNone(jobs.parse_stage('@@STAGE x/y nope'))


if __name__ == '__main__':
    unittest.main()
