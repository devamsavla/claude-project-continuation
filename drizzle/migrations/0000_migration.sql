CREATE TABLE public.waitlist (
  id bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
  email text NOT NULL UNIQUE,
  phone text,
  interest text,
  source text DEFAULT 'website',
  created_at timestamptz NOT NULL DEFAULT now()
);
GRANT ALL ON public.waitlist TO service_role;
ALTER TABLE public.waitlist ENABLE ROW LEVEL SECURITY;
-- No direct client policies: visitors join only through join_waitlist below.

CREATE OR REPLACE FUNCTION public.join_waitlist(p_email text, p_interest text DEFAULT NULL, p_source text DEFAULT 'website')
RETURNS TABLE(is_new boolean, "position" bigint)
LANGUAGE plpgsql
SECURITY DEFINER
SET search_path = public
AS $$
DECLARE
  v_email text := lower(trim(p_email));
  v_rows int;
BEGIN
  IF v_email IS NULL OR v_email !~ '^[^@\s]+@[^@\s]+\.[^@\s]+$' OR length(v_email) > 254 THEN
    RAISE EXCEPTION 'Please enter a valid email address.';
  END IF;
  INSERT INTO public.waitlist(email, interest, source)
  VALUES (v_email, left(p_interest, 40), left(coalesce(p_source, 'website'), 40))
  ON CONFLICT (email) DO NOTHING;
  GET DIAGNOSTICS v_rows = ROW_COUNT;
  RETURN QUERY SELECT v_rows > 0, (SELECT count(*) FROM public.waitlist);
END;
$$;
REVOKE ALL ON FUNCTION public.join_waitlist(text, text, text) FROM PUBLIC;
GRANT EXECUTE ON FUNCTION public.join_waitlist(text, text, text) TO anon, authenticated;