/**
 * Elo ratings, shared by every league tab.
 *
 * All three tabs ran their own copy of this loop. The maths never differed —
 * only the constants and the margin-of-victory multiplier, which is genuinely
 * sport-specific (football uses goal difference bands, the NFL a log of points,
 * the NBA a power curve). Those are parameters; the loop is not.
 *
 *   Elo.run(games, opts) -> { ratings, history, ratingTrail, lastPlayed }
 *
 *   games  chronological [{ date, season, home, away, hg, ag, neutral? }]
 *   opts   { K, homeAdv, regress, defaultRating, mov(margin, winnerDiff) }
 *
 *          regress is the fraction of a team's rating gap KEPT across a season
 *          boundary: 0.9 keeps most of it, 0.5 pulls half back to the mean.
 *          mov receives the signed margin and the rating gap from the winner's
 *          point of view, which is what the autocorrelation correction needs.
 *
 * Ratings, history and trail come back in the shape the pages already render,
 * so this is a drop-in for the three functions it replaces.
 */
(function (global) {
  'use strict';

  function outcome(gf, ga) {
    return gf > ga ? 'W' : gf < ga ? 'L' : 'D';
  }

  function run(games, opts) {
    var K = opts.K;
    var HOME = opts.homeAdv;
    var REGRESS = opts.regress;
    var BASE = opts.defaultRating;
    var mov = opts.mov;

    var ratings = {}, history = {}, ratingTrail = {}, lastPlayed = {};
    var prevSeason = null;

    function get(t) {
      return Object.prototype.hasOwnProperty.call(ratings, t) ? ratings[t] : BASE;
    }

    for (var i = 0; i < games.length; i++) {
      var g = games[i];

      if (prevSeason !== null && g.season !== prevSeason) {
        for (var t in ratings) {
          ratings[t] = BASE + (ratings[t] - BASE) * REGRESS;
        }
        lastPlayed = {};              // rest resets over an offseason
      }
      prevSeason = g.season;

      var home = g.home, away = g.away;
      var Rh = get(home), Ra = get(away);
      var dr = Rh - Ra + (g.neutral ? 0 : HOME);
      var expected = 1 / (1 + Math.pow(10, -dr / 400));
      var margin = g.hg - g.ag;
      var actual = margin > 0 ? 1 : margin < 0 ? 0 : 0.5;
      // The multiplier sees the gap from the winner's side, so a favourite
      // winning big is damped and an upset is not.
      var mult = margin === 0 ? 1 : mov(margin, margin > 0 ? dr : -dr);
      var delta = K * mult * (actual - expected);

      ratings[home] = Rh + delta;
      ratings[away] = Ra - delta;

      // carry match context so the chart can explain each move
      (ratingTrail[home] = ratingTrail[home] || []).push({
        date: g.date, rating: ratings[home], delta: delta, opp: away,
        venue: 'home', gf: g.hg, ga: g.ag, result: outcome(g.hg, g.ag)
      });
      (ratingTrail[away] = ratingTrail[away] || []).push({
        date: g.date, rating: ratings[away], delta: -delta, opp: home,
        venue: 'away', gf: g.ag, ga: g.hg, result: outcome(g.ag, g.hg)
      });

      (history[home] = history[home] || []).push({
        date: g.date, opponent: away, venue: 'home', gf: g.hg, ga: g.ag,
        result: outcome(g.hg, g.ag), season: g.season
      });
      (history[away] = history[away] || []).push({
        date: g.date, opponent: home, venue: 'away', gf: g.ag, ga: g.hg,
        result: outcome(g.ag, g.hg), season: g.season
      });

      if (g.date) {
        var d = Math.floor(Date.parse(g.date + 'T00:00:00Z') / 86400000);
        lastPlayed[home] = d;
        lastPlayed[away] = d;
      }
    }

    return { ratings: ratings, history: history,
             ratingTrail: ratingTrail, lastPlayed: lastPlayed };
  }

  /** Win probability from a rating gap, as log-odds so callers can add to it. */
  function logOdds(Rh, Ra, homeAdv) {
    return Math.log(10) * (Rh - Ra + (homeAdv || 0)) / 400;
  }

  /** Sport-specific margin-of-victory multipliers. */
  var mov = {
    // Football: goal-difference bands. Small integers, so a curve is overkill.
    football: function (margin) {
      var gd = Math.abs(margin);
      if (gd <= 1) return 1;
      if (gd === 2) return 1.5;
      return (11 + gd) / 8;
    },
    // NFL: log of points, with FiveThirtyEight's autocorrelation correction.
    nfl: function (margin, winnerDiff) {
      return Math.log(Math.abs(margin) + 1) * (2.2 / (winnerDiff * 0.001 + 2.2));
    },
    // NBA: power curve; larger scores need a flatter response than a log.
    nba: function (margin, winnerDiff) {
      return Math.pow(Math.abs(margin) + 3, 0.8) / (7.5 + 0.006 * winnerDiff);
    }
  };

  global.Elo = { run: run, logOdds: logOdds, mov: mov };
})(window);
